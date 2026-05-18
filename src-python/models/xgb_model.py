"""
models/xgb_model.py — XGBoost による FX 売買予測モデル
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb

from models.base_model import BaseModel
from utils.logger import get_logger

logger = get_logger(__name__)

_LABEL_ENCODE = {-1: 0, 0: 1, 1: 2}
_LABEL_DECODE = {0: -1, 1: 0, 2: 1}


class XGBModel(BaseModel):
    DEFAULT_PARAMS = {
        "objective":        "multi:softprob",
        "num_class":        3,
        "eval_metric":      "mlogloss",
        "n_estimators":     500,
        "learning_rate":    0.05,
        "max_depth":        6,
        "min_child_weight": 3,
        "subsample":        0.8,
        "colsample_bytree": 0.8,
        "gamma":            0.1,
        "reg_alpha":        0.1,
        "reg_lambda":       1.0,
        "random_state":     42,
        "n_jobs":           -1,
        "verbosity":        0,
        "early_stopping_rounds": 30,
    }

    def __init__(self, params: Optional[dict] = None):
        super().__init__(name="XGBModel")
        self.params = {**self.DEFAULT_PARAMS, **(params or {})}
        self._model: Optional[xgb.XGBClassifier] = None
        self._feature_names: list[str] = []

    def train(self, X_train, y_train, X_val=None, y_val=None) -> "XGBModel":
        logger.info(f"XGBoost 学習開始: {X_train.shape}")
        self._feature_names = list(X_train.columns)
        y_tr = y_train.map(_LABEL_ENCODE)

        self._model = xgb.XGBClassifier(**self.params)

        fit_kwargs: dict = {"verbose": False}
        if X_val is not None and y_val is not None:
            y_v = y_val.map(_LABEL_ENCODE)
            fit_kwargs["eval_set"] = [(X_val, y_v)]

        self._model.fit(X_train, y_tr, **fit_kwargs)
        logger.info("XGBoost 学習完了")
        self.is_fitted = True
        return self

    def predict(self, X) -> np.ndarray:
        self._check_fitted()
        raw = self._model.predict(X)
        return np.array([_LABEL_DECODE[int(r)] for r in raw])

    def predict_proba(self, X) -> np.ndarray:
        self._check_fitted()
        return self._model.predict_proba(X)

    def save(self, path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": self._model, "features": self._feature_names}, path)
        logger.info(f"保存: {path}")

    def load(self, path) -> "XGBModel":
        data = joblib.load(path)
        self._model = data["model"]
        self._feature_names = data["features"]
        self.is_fitted = True
        return self

    def feature_importance(self, top_n: int = 20) -> pd.DataFrame:
        self._check_fitted()
        return pd.DataFrame({
            "feature":    self._feature_names,
            "importance": self._model.feature_importances_,
        }).sort_values("importance", ascending=False).head(top_n).reset_index(drop=True)
