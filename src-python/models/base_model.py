"""
src/models/base_model.py — AI モデルの抽象基底クラス
全モデルはこのインターフェースを継承して実装する
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix

from utils.logger import get_logger

logger = get_logger(__name__)


class BaseModel(ABC):
    """
    全予測モデルの共通インターフェース。

    継承クラスは以下を実装すること:
      - train()   : 学習
      - predict() : クラス予測（1=BUY, -1=SELL, 0=HOLD）
      - predict_proba() : クラス確率の予測
      - save() / load() : モデルの永続化
    """

    def __init__(self, name: str = "base"):
        self.name      = name
        self.is_fitted = False
        self._model    = None

    # ─────────────────────────────────────────────────────────────────────────
    # 抽象メソッド（サブクラスで実装必須）
    # ─────────────────────────────────────────────────────────────────────────

    @abstractmethod
    def train(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val:   Optional[pd.DataFrame] = None,
        y_val:   Optional[pd.Series]    = None,
    ) -> "BaseModel":
        """モデルを学習する"""
        ...

    @abstractmethod
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """クラスラベルを予測する（1, -1, 0）"""
        ...

    @abstractmethod
    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """各クラスの確率を返す（shape: [n_samples, n_classes]）"""
        ...

    @abstractmethod
    def save(self, path: str | Path) -> None:
        """モデルをファイルに保存する"""
        ...

    @abstractmethod
    def load(self, path: str | Path) -> "BaseModel":
        """ファイルからモデルを読み込む"""
        ...

    # ─────────────────────────────────────────────────────────────────────────
    # 共通メソッド（継承クラスで利用可）
    # ─────────────────────────────────────────────────────────────────────────

    def evaluate(
        self,
        X_test: pd.DataFrame,
        y_test: pd.Series,
        verbose: bool = True,
    ) -> dict:
        """
        テストデータでモデルを評価し、指標を返す。

        Returns
        -------
        dict: accuracy, precision, recall, f1, confusion_matrix
        """
        self._check_fitted()
        y_pred = self.predict(X_test)

        # LSTM など系列モデルは seq_len 分出力が短い → 末尾を揃えて比較する
        if len(y_pred) != len(y_test):
            k = min(len(y_pred), len(y_test))
            y_pred = y_pred[-k:]
            y_test = y_test.iloc[-k:]

        report = classification_report(
            y_test, y_pred,
            labels=[-1, 0, 1],
            target_names=["SELL", "HOLD", "BUY"],
            output_dict=True,
            zero_division=0,
        )
        cm = confusion_matrix(y_test, y_pred, labels=[-1, 0, 1])

        metrics = {
            "accuracy":  report["accuracy"],
            "precision": report["weighted avg"]["precision"],
            "recall":    report["weighted avg"]["recall"],
            "f1":        report["weighted avg"]["f1-score"],
            "confusion_matrix": cm.tolist(),
            "report":    report,
        }

        if verbose:
            logger.info(f"\n{'='*50}")
            logger.info(f"モデル評価: {self.name}")
            logger.info(f"Accuracy:  {metrics['accuracy']:.4f}")
            logger.info(f"F1 Score:  {metrics['f1']:.4f}")
            logger.info(
                f"\n{classification_report(y_test, y_pred, labels=[-1,0,1], target_names=['SELL','HOLD','BUY'], zero_division=0)}"
            )

        return metrics

    def signal(self, X: pd.DataFrame) -> dict:
        """
        最新行のシグナルと信頼度を返す（リアルタイム推論用）。

        Returns
        -------
        dict: label, confidence, probabilities
        """
        self._check_fitted()
        latest = X.iloc[[-1]]  # 最新の1行
        proba  = self.predict_proba(latest)[0]
        label  = self.predict(latest)[0]

        label_map = {-1: "SELL", 0: "HOLD", 1: "BUY"}
        return {
            "label":       label_map.get(label, "HOLD"),
            "raw_label":   int(label),
            "confidence":  float(np.max(proba)),
            "probabilities": {
                "SELL": float(proba[0]),
                "HOLD": float(proba[1]),
                "BUY":  float(proba[2]),
            },
        }

    def _check_fitted(self):
        if not self.is_fitted:
            raise RuntimeError(
                f"{self.name} はまだ学習されていません。train() を先に呼び出してください。"
            )
