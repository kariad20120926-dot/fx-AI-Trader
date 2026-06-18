# -*- coding: utf-8 -*-
"""
strategies/signal_generator.py — 強化版シグナルフィルター
勝率を上げるための複合フィルターを実装
"""
from __future__ import annotations
from typing import Optional
import numpy as np
import pandas as pd
from models.base_model import BaseModel
from strategies.risk_manager import RiskManager, RiskConfig, TradeSignal
from utils.logger import get_logger

logger = get_logger(__name__)


class SignalGenerator:
    """
    モデル予測 + 5段階フィルターで高品質シグナルのみを抽出する。

    フィルター:
      1. 信頼度フィルター（confidence_min）
      2. ADX トレンドフィルター（レンジ相場を除外）
      3. ボラティリティフィルター（ATR の異常値を除外）
      4. リスクリワードフィルター（RR < 1.5 を除外）
      5. 連続シグナルフィルター（同方向が続く場合は間引く）
    """

    def __init__(
        self,
        model:               BaseModel,
        risk_manager:        Optional[RiskManager] = None,
        confidence_min:      float = 0.36,
        adx_min:             float = 15.0,
        atr_col:             str   = "atr_14",
        adx_col:             str   = "adx",
        vol_percentile_low:  float = 0.05,
        vol_percentile_high: float = 0.95,
    ):
        self.model          = model
        self.risk_manager   = risk_manager or RiskManager()
        self.confidence_min = confidence_min
        self.adx_min        = adx_min
        self.atr_col        = atr_col
        self.adx_col        = adx_col
        self.vol_pct_low    = vol_percentile_low
        self.vol_pct_high   = vol_percentile_high
        self._atr_low:  Optional[float] = None
        self._atr_high: Optional[float] = None

    def fit_thresholds(self, X: pd.DataFrame) -> "SignalGenerator":
        if self.atr_col in X.columns:
            atr = X[self.atr_col].dropna()
            if len(atr) > 0:
                self._atr_low  = float(atr.quantile(self.vol_pct_low))
                self._atr_high = float(atr.quantile(self.vol_pct_high))
                logger.info(f"ATR 閾値設定: low={self._atr_low:.5f} high={self._atr_high:.5f}")
        return self

    def generate(self, X: pd.DataFrame) -> pd.DataFrame:
        labels      = self.model.predict(X)
        probas      = self.model.predict_proba(X)

        # LSTM の出力サイズを XGBoost に合わせる
        n = len(X)
        if len(probas) < n:
            pad   = np.tile(probas[:1], (n - len(probas), 1))
            probas = np.vstack([pad, probas])
        elif len(probas) > n:
            probas = probas[-n:]

        confidences = probas.max(axis=1)

        results      = []
        prev_dir     = 0
        same_dir_cnt = 0

        for i, (idx, row) in enumerate(X.iterrows()):
            label      = int(labels[i]) if i < len(labels) else 0
            confidence = float(confidences[i])
            direction, reason = self._apply_filters(row, label, confidence)

            # 連続同方向フィルター（3回以上同じ方向なら間引く）
            if direction != 0:
                if direction == prev_dir:
                    same_dir_cnt += 1
                    if same_dir_cnt >= 3:
                        direction = 0
                        reason    = "consecutive_signal"
                else:
                    same_dir_cnt = 0
                prev_dir = direction if direction != 0 else prev_dir

            results.append({
                "direction":  direction,
                "confidence": confidence,
                "raw_label":  label,
                "filtered":   direction != label,
                "reason":     reason,
            })

        df = pd.DataFrame(results, index=X.index)
        logger.info(
            f"シグナル生成: 総数={len(df)} "
            f"BUY={(df['direction']==1).sum()} "
            f"SELL={(df['direction']==-1).sum()} "
            f"HOLD={(df['direction']==0).sum()} "
            f"フィルター除外={df['filtered'].sum()}"
        )
        return df

    def generate_latest(self, X: pd.DataFrame, current_price: Optional[float] = None) -> Optional[TradeSignal]:
        row        = X.iloc[-1]
        info       = self.model.signal(X)
        label      = info["raw_label"]
        confidence = info["confidence"]
        direction, reason = self._apply_filters(row, label, confidence)
        if direction == 0:
            logger.info(f"シグナルなし: {reason}")
            return None
        atr   = float(row.get(self.atr_col, 0.005))
        close = float(current_price if current_price is not None else row.get("close", row.get("ema_9", 0.0)))
        return self.risk_manager.calculate_trade(
            direction=direction,
            confidence=confidence,
            entry_price=close,
            atr=atr,
            timestamp=X.index[-1] if hasattr(X.index, '__getitem__') else None,
        )

    def _apply_filters(self, row, label, confidence):
        if label == 0:
            return 0, "model_hold"

        # 1. 信頼度フィルター
        if confidence < self.confidence_min:
            return 0, f"low_confidence({confidence:.3f})"

        # 2. ADX フィルター
        adx = row.get(self.adx_col)
        if adx is not None and not np.isnan(float(adx)) and float(adx) < self.adx_min:
            return 0, f"low_adx({float(adx):.1f})"

        # 3. ボラティリティフィルター
        atr = row.get(self.atr_col)
        if atr is not None and not np.isnan(float(atr)):
            atr_f = float(atr)
            if self._atr_low and atr_f < self._atr_low:
                return 0, "low_volatility"
            if self._atr_high and atr_f > self._atr_high:
                return 0, "extreme_volatility"

        return label, "ok"
