"""
src/models/lstm_model.py — LSTM による時系列予測モデル（PyTorch）
Attention 機構付きの双方向 LSTM で FX チャートの時系列パターンを学習する
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from models.base_model import BaseModel
from utils.logger import get_logger

logger = get_logger(__name__)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


# ─────────────────────────────────────────────────────────────────────────────
# ニューラルネットワーク定義
# ─────────────────────────────────────────────────────────────────────────────

class _AttentionLayer(nn.Module):
    """Scaled Dot-Product Attention（LSTM 出力に適用）"""

    def __init__(self, hidden_dim: int):
        super().__init__()
        self.attn = nn.Linear(hidden_dim, 1)

    def forward(self, lstm_out: torch.Tensor) -> torch.Tensor:
        # lstm_out: [batch, seq_len, hidden_dim]
        scores  = self.attn(lstm_out).squeeze(-1)          # [batch, seq_len]
        weights = torch.softmax(scores, dim=1).unsqueeze(-1) # [batch, seq_len, 1]
        context = (lstm_out * weights).sum(dim=1)           # [batch, hidden_dim]
        return context


class _LSTMNet(nn.Module):
    """双方向 LSTM + Attention + 分類ヘッド"""

    def __init__(
        self,
        input_dim:   int,
        hidden_dim:  int = 128,
        num_layers:  int = 2,
        num_classes: int = 3,
        dropout:     float = 0.3,
        bidirectional: bool = True,
    ):
        super().__init__()
        self.bidirectional = bidirectional
        factor = 2 if bidirectional else 1

        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
            bidirectional=bidirectional,
        )
        self.attention = _AttentionLayer(hidden_dim * factor)
        self.norm      = nn.LayerNorm(hidden_dim * factor)
        self.dropout   = nn.Dropout(dropout)
        self.fc = nn.Sequential(
            nn.Linear(hidden_dim * factor, 64),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(64, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        lstm_out, _ = self.lstm(x)          # [batch, seq_len, hidden*factor]
        context     = self.attention(lstm_out)
        context     = self.norm(context)
        context     = self.dropout(context)
        return self.fc(context)             # [batch, num_classes]


# ─────────────────────────────────────────────────────────────────────────────
# モデルクラス
# ─────────────────────────────────────────────────────────────────────────────

class LSTMModel(BaseModel):
    """
    双方向 LSTM + Attention による FX 売買予測モデル。

    入力: [batch, seq_len, n_features] の時系列テンソル
    出力: 3クラス（SELL=-1, HOLD=0, BUY=1）
    """

    LABEL_MAP    = {-1: 0, 0: 1, 1: 2}
    LABEL_DECODE = {0: -1, 1: 0, 2: 1}

    def __init__(
        self,
        seq_len:    int   = 30,      # 何本分の過去データを使うか
        hidden_dim: int   = 128,
        num_layers: int   = 2,
        dropout:    float = 0.3,
        lr:         float = 1e-3,
        epochs:     int   = 50,
        batch_size: int   = 64,
        patience:   int   = 10,      # Early stopping
    ):
        super().__init__(name="LSTMModel")
        self.seq_len    = seq_len
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers
        self.dropout    = dropout
        self.lr         = lr
        self.epochs     = epochs
        self.batch_size = batch_size
        self.patience   = patience
        self._net: Optional[_LSTMNet] = None
        self._feature_names: list[str] = []
        logger.info(f"LSTMModel 初期化 (device={DEVICE})")

    # ─────────────────────────────────────────────────────────────────────────

    def train(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val:   Optional[pd.DataFrame] = None,
        y_val:   Optional[pd.Series]    = None,
    ) -> "LSTMModel":
        self._feature_names = list(X_train.columns)
        input_dim = X_train.shape[1]

        self._net = _LSTMNet(
            input_dim=input_dim,
            hidden_dim=self.hidden_dim,
            num_layers=self.num_layers,
            dropout=self.dropout,
        ).to(DEVICE)

        # データローダーの構築
        train_loader = self._make_loader(X_train, y_train, shuffle=True)
        val_loader   = self._make_loader(X_val, y_val) if X_val is not None else None

        optimizer = torch.optim.AdamW(self._net.parameters(), lr=self.lr, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=self.epochs)
        criterion = nn.CrossEntropyLoss()

        best_val_loss  = float("inf")
        patience_count = 0
        best_state     = None

        logger.info(f"LSTM 学習開始: epochs={self.epochs} batch={self.batch_size} seq={self.seq_len}")

        for epoch in range(1, self.epochs + 1):
            train_loss = self._train_epoch(train_loader, optimizer, criterion)
            scheduler.step()

            if val_loader:
                val_loss = self._eval_epoch(val_loader, criterion)
                if epoch % 5 == 0:
                    logger.info(f"Epoch {epoch:3d}/{self.epochs} | train={train_loss:.4f} val={val_loss:.4f}")

                if val_loss < best_val_loss:
                    best_val_loss  = val_loss
                    best_state     = {k: v.cpu().clone() for k, v in self._net.state_dict().items()}
                    patience_count = 0
                else:
                    patience_count += 1
                    if patience_count >= self.patience:
                        logger.info(f"Early stopping at epoch {epoch}")
                        break
            else:
                if epoch % 10 == 0:
                    logger.info(f"Epoch {epoch:3d}/{self.epochs} | train={train_loss:.4f}")

        # 最良の重みを復元
        if best_state:
            self._net.load_state_dict({k: v.to(DEVICE) for k, v in best_state.items()})

        self.is_fitted = True
        logger.info(f"LSTM 学習完了 (best_val_loss={best_val_loss:.4f})")
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        self._check_fitted()
        proba = self.predict_proba(X)
        encoded = np.argmax(proba, axis=1)
        return np.array([self.LABEL_DECODE[int(e)] for e in encoded])

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        self._check_fitted()
        self._net.eval()
        X_seq = self._make_sequences(X.values)
        tensor = torch.FloatTensor(X_seq).to(DEVICE)
        with torch.no_grad():
            logits = self._net(tensor)
            proba  = torch.softmax(logits, dim=1).cpu().numpy()
        return proba

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save({
            "state_dict":    self._net.state_dict(),
            "feature_names": self._feature_names,
            "config": {
                "input_dim":  len(self._feature_names),
                "hidden_dim": self.hidden_dim,
                "num_layers": self.num_layers,
                "dropout":    self.dropout,
                "seq_len":    self.seq_len,
            },
        }, path)
        logger.info(f"LSTM モデルを保存: {path}")

    def load(self, path: str | Path) -> "LSTMModel":
        ckpt = torch.load(path, map_location=DEVICE)
        cfg  = ckpt["config"]
        self._net = _LSTMNet(
            input_dim=cfg["input_dim"],
            hidden_dim=cfg["hidden_dim"],
            num_layers=cfg["num_layers"],
            dropout=cfg["dropout"],
        ).to(DEVICE)
        self._net.load_state_dict(ckpt["state_dict"])
        self._feature_names = ckpt["feature_names"]
        self.seq_len        = cfg["seq_len"]
        self.is_fitted      = True
        logger.info(f"LSTM モデルを読み込み: {path}")
        return self

    # ─────────────────────────────────────────────────────────────────────────
    # プライベートメソッド
    # ─────────────────────────────────────────────────────────────────────────

    def _make_sequences(self, X: np.ndarray) -> np.ndarray:
        """2D 配列 → [n, seq_len, features] の3Dシーケンスに変換"""
        n = len(X)
        if n < self.seq_len:
            # パディング（先頭を繰り返す）
            pad = np.repeat(X[[0]], self.seq_len - n, axis=0)
            X   = np.vstack([pad, X])
            n   = len(X)
        seqs = np.stack([X[i:i + self.seq_len] for i in range(n - self.seq_len + 1)])
        return seqs  # [n - seq_len + 1, seq_len, features]

    def _make_loader(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        shuffle: bool = False,
    ) -> DataLoader:
        X_seq   = self._make_sequences(X.values)
        # ラベルを seq 数に合わせてトリム（先頭の seq_len-1 行は使えない）
        y_enc   = y.map(self.LABEL_MAP).values[self.seq_len - 1:]
        dataset = TensorDataset(
            torch.FloatTensor(X_seq),
            torch.LongTensor(y_enc),
        )
        return DataLoader(dataset, batch_size=self.batch_size, shuffle=shuffle, drop_last=False)

    def _train_epoch(self, loader: DataLoader, optimizer, criterion) -> float:
        self._net.train()
        total_loss = 0.0
        for X_batch, y_batch in loader:
            X_batch, y_batch = X_batch.to(DEVICE), y_batch.to(DEVICE)
            optimizer.zero_grad()
            logits = self._net(X_batch)
            loss   = criterion(logits, y_batch)
            loss.backward()
            nn.utils.clip_grad_norm_(self._net.parameters(), max_norm=1.0)
            optimizer.step()
            total_loss += loss.item() * len(X_batch)
        return total_loss / len(loader.dataset)

    def _eval_epoch(self, loader: DataLoader, criterion) -> float:
        self._net.eval()
        total_loss = 0.0
        with torch.no_grad():
            for X_batch, y_batch in loader:
                X_batch, y_batch = X_batch.to(DEVICE), y_batch.to(DEVICE)
                logits = self._net(X_batch)
                loss   = criterion(logits, y_batch)
                total_loss += loss.item() * len(X_batch)
        return total_loss / len(loader.dataset)
