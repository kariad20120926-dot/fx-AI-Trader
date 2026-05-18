"""
src/models/ensemble.py — アンサンブルモデル
XGBoost・LSTM の予測確率を重み付きで統合し、最終シグナルを生成する
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd

from models.base_model import BaseModel
from models.xgb_model import XGBModel
from models.lstm_model import LSTMModel
from utils.logger import get_logger

logger = get_logger(__name__)

LABEL_DECODE = {0: -1, 1: 0, 2: 1}


class EnsembleModel(BaseModel):
    """
    XGBoost + LSTM のスタッキングアンサンブル。

    統合方式（strategy パラメータで選択）:
      - "weighted_avg" : 重み付き平均（デフォルト）
      - "vote"         : 多数決
      - "confidence"   : 最高信頼度モデルの予測を採用

    confidence_threshold を設定すると、
    最高確率が閾値未満の場合は HOLD を出力する（過剰取引防止）。
    """

    def __init__(
        self,
        xgb_weight:           float = 0.5,
        lstm_weight:          float = 0.5,
        strategy:             str   = "weighted_avg",
        confidence_threshold: float = 0.45,
        xgb_params:           Optional[dict] = None,
        lstm_params:          Optional[dict] = None,
    ):
        super().__init__(name="EnsembleModel")
        assert abs(xgb_weight + lstm_weight - 1.0) < 1e-6, "重みの合計は 1.0 にしてください"

        self.xgb_weight           = xgb_weight
        self.lstm_weight          = lstm_weight
        self.strategy             = strategy
        self.confidence_threshold = confidence_threshold

        self.xgb  = XGBModel(params=xgb_params)
        self.lstm = LSTMModel(**(lstm_params or {}))

    # ─────────────────────────────────────────────────────────────────────────
    # BaseModel 実装
    # ─────────────────────────────────────────────────────────────────────────

    def train(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val:   Optional[pd.DataFrame] = None,
        y_val:   Optional[pd.Series]    = None,
    ) -> "EnsembleModel":
        """XGBoost と LSTM を並列で学習する"""
        logger.info("アンサンブル学習開始")

        logger.info("--- XGBoost 学習 ---")
        self.xgb.train(X_train, y_train, X_val, y_val)

        logger.info("--- LSTM 学習 ---")
        self.lstm.train(X_train, y_train, X_val, y_val)

        self.is_fitted = True
        logger.info("アンサンブル学習完了")
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        self._check_fitted()
        proba  = self.predict_proba(X)
        labels = np.argmax(proba, axis=1)

        # 信頼度が閾値未満なら HOLD に変更
        max_conf = np.max(proba, axis=1)
        labels[max_conf < self.confidence_threshold] = 1  # 1 = HOLD (encoded)

        return np.array([LABEL_DECODE[int(l)] for l in labels])

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """統合後のクラス確率を返す（shape: [n_samples, 3]）"""
        self._check_fitted()

        xgb_proba  = self.xgb.predict_proba(X)   # [n, 3]
        lstm_proba = self.lstm.predict_proba(X)   # [m, 3] (m <= n due to seq_len)

        # LSTMの出力サイズをXGBoostに合わせる（末尾をパディング）
        n = len(xgb_proba)
        m = len(lstm_proba)
        if m < n:
            pad = np.tile(lstm_proba[-1:], (n - m, 1))
            lstm_proba = np.vstack([pad, lstm_proba])
        elif m > n:
            lstm_proba = lstm_proba[-n:]

        if self.strategy == "weighted_avg":
            return self.xgb_weight * xgb_proba + self.lstm_weight * lstm_proba

        elif self.strategy == "vote":
            xgb_pred  = np.argmax(xgb_proba,  axis=1)
            lstm_pred = np.argmax(lstm_proba, axis=1)
            # 一致すればその確率、不一致なら HOLD
            agreed    = (xgb_pred == lstm_pred)
            result    = np.zeros((len(X), 3))
            result[:, 1] = 1.0  # デフォルト HOLD
            for i, (a, xp, xproba, lproba) in enumerate(
                zip(agreed, xgb_pred, xgb_proba, lstm_proba)
            ):
                if a:
                    result[i] = (xproba + lproba) / 2
            return result

        elif self.strategy == "confidence":
            xgb_conf  = np.max(xgb_proba,  axis=1, keepdims=True)
            lstm_conf = np.max(lstm_proba, axis=1, keepdims=True)
            use_xgb   = (xgb_conf >= lstm_conf)
            return np.where(use_xgb, xgb_proba, lstm_proba)

        else:
            raise ValueError(f"不明な strategy: {self.strategy}")

    def save(self, directory: str | Path) -> None:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.xgb.save(directory / "xgb.joblib")
        self.lstm.save(directory / "lstm.pt")
        joblib.dump({
            "xgb_weight":           self.xgb_weight,
            "lstm_weight":          self.lstm_weight,
            "strategy":             self.strategy,
            "confidence_threshold": self.confidence_threshold,
        }, directory / "ensemble_config.joblib")
        logger.info(f"アンサンブルモデルを保存: {directory}")

    def load(self, directory: str | Path) -> "EnsembleModel":
        directory = Path(directory)
        self.xgb.load(directory / "xgb.joblib")
        self.lstm.load(directory / "lstm.pt")
        cfg = joblib.load(directory / "ensemble_config.joblib")
        self.xgb_weight           = cfg["xgb_weight"]
        self.lstm_weight          = cfg["lstm_weight"]
        self.strategy             = cfg["strategy"]
        self.confidence_threshold = cfg["confidence_threshold"]
        self.is_fitted            = True
        logger.info(f"アンサンブルモデルを読み込み: {directory}")
        return self

    # ─────────────────────────────────────────────────────────────────────────
    # アンサンブル固有の機能
    # ─────────────────────────────────────────────────────────────────────────

    def evaluate_each(
        self,
        X_test: pd.DataFrame,
        y_test: pd.Series,
    ) -> dict:
        """個別モデルとアンサンブル全体の評価指標を比較する"""
        results = {
            "XGBoost":  self.xgb.evaluate(X_test, y_test, verbose=False),
            "LSTM":     self.lstm.evaluate(X_test, y_test, verbose=False),
            "Ensemble": self.evaluate(X_test, y_test, verbose=False),
        }
        logger.info("\n=== モデル比較 ===")
        for model_name, metrics in results.items():
            logger.info(
                f"{model_name:10s} | Acc={metrics['accuracy']:.4f} "
                f"F1={metrics['f1']:.4f}"
            )
        return results

    def optimize_weights(
        self,
        X_val: pd.DataFrame,
        y_val: pd.Series,
        steps: int = 20,
    ) -> tuple[float, float]:
        """
        検証データ上で XGBoost/LSTM の最適な重みを探索する。

        Returns
        -------
        (xgb_weight, lstm_weight): 最適な重みのペア
        """
        from sklearn.metrics import f1_score

        best_f1 = -1.0
        best_w  = (self.xgb_weight, self.lstm_weight)

        xgb_proba  = self.xgb.predict_proba(X_val)
        lstm_proba = self.lstm.predict_proba(X_val)

        for i in range(steps + 1):
            w = i / steps
            combined  = w * xgb_proba + (1 - w) * lstm_proba
            preds_enc = np.argmax(combined, axis=1)
            preds     = np.array([LABEL_DECODE[int(p)] for p in preds_enc])
            f1 = f1_score(y_val, preds, average="weighted", zero_division=0)
            if f1 > best_f1:
                best_f1 = f1
                best_w  = (round(w, 2), round(1 - w, 2))

        self.xgb_weight, self.lstm_weight = best_w
        logger.info(
            f"最適重み: XGB={self.xgb_weight:.2f} LSTM={self.lstm_weight:.2f} "
            f"(val_f1={best_f1:.4f})"
        )
        return best_w
