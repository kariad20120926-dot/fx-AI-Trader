# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd
from utils.logger import get_logger

logger = get_logger(__name__)


def pip_size_for(instrument: str) -> float:
    """通貨ペアからpip幅を返す（JPYクロス=0.01、それ以外=0.0001）"""
    return 0.01 if "JPY" in instrument.upper() else 0.0001


@dataclass
class RiskConfig:
    initial_capital:   float = 1_000_000.0
    risk_per_trade:    float = 0.02
    max_position_pct:  float = 0.10   # 証拠金使用率の上限（資金に対する割合）
    sl_atr_mult:       float = 2.0
    tp_atr_mult:       float = 3.0
    risk_reward_min:   float = 1.0   # 1.5 から 1.2 に変更
    max_drawdown_pct:  float = 0.20
    daily_loss_limit:  float = 0.05
    spread_pips:       float = 0.3   # 往復の総スプレッド（bid/ask差）
    slippage_pips:     float = 0.1   # 成行・ストップ約定時の滑り
    commission_pct:    float = 0.0002
    pip_value:         float = 0.01
    lot_size:          int   = 1000
    leverage:          float = 25.0  # 国内FX標準
    # ── トレード管理（0 = 無効） ──────────────────────────────────────
    trailing_atr_mult: float = 0.0   # 有利方向の極値から ATR×この値 でSLを追従
    breakeven_rr:      float = 0.0   # 含み益がSL距離×この値に達したらSLを建値へ
    max_hold_bars:     int   = 0     # 最大保有バー数（超過で時間切れ決済）
    confidence_sizing: bool  = True  # 信頼度に応じてロットを増減（ライブと整合）


@dataclass
class TradeSignal:
    direction:    int
    confidence:   float
    entry_price:  float
    stop_loss:    float
    take_profit:  float
    lot_size:     float
    risk_amount:  float
    risk_reward:  float
    timestamp:    Optional[pd.Timestamp] = None


@dataclass
class PortfolioState:
    capital:       float
    peak_capital:  float
    daily_start:   float
    open_trades:   list = field(default_factory=list)

    @property
    def drawdown(self) -> float:
        return (self.peak_capital - self.capital) / self.peak_capital

    @property
    def daily_loss(self) -> float:
        return (self.daily_start - self.capital) / self.daily_start


class RiskManager:
    def __init__(self, config: Optional[RiskConfig] = None):
        self.cfg   = config or RiskConfig()
        self.state = PortfolioState(
            capital=self.cfg.initial_capital,
            peak_capital=self.cfg.initial_capital,
            daily_start=self.cfg.initial_capital,
        )

    def calculate_trade(
        self,
        direction:   int,
        confidence:  float,
        entry_price: float,
        atr:         float,
        timestamp:   Optional[pd.Timestamp] = None,
    ) -> Optional[TradeSignal]:
        if direction == 0:
            return None
        if not self._portfolio_check():
            return None

        sl_dist = atr * self.cfg.sl_atr_mult
        tp_dist = atr * self.cfg.tp_atr_mult

        if direction == 1:
            stop_loss   = entry_price - sl_dist
            take_profit = entry_price + tp_dist
        else:
            stop_loss   = entry_price + sl_dist
            take_profit = entry_price - tp_dist

        risk_reward = tp_dist / (sl_dist + 1e-10)
        if risk_reward < self.cfg.risk_reward_min:
            logger.debug(f"RR比不足でスキップ: {risk_reward:.2f} < {self.cfg.risk_reward_min}")
            return None

        confidence_scale = 0.5 + 0.5 * min(confidence, 1.0)
        risk_amount  = self.state.capital * self.cfg.risk_per_trade * confidence_scale
        risk_per_lot = sl_dist * self.cfg.pip_value * self.cfg.lot_size
        lots         = max(1, int(risk_amount / (risk_per_lot + 1e-10)))
        max_lots     = max(1, int(self.state.capital * self.cfg.max_position_pct / (entry_price * self.cfg.lot_size + 1e-10)))
        lots         = min(lots, max_lots)
        actual_risk  = risk_per_lot * lots

        return TradeSignal(
            direction=direction,
            confidence=confidence,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            lot_size=lots * self.cfg.lot_size,
            risk_amount=actual_risk,
            risk_reward=risk_reward,
            timestamp=timestamp,
        )

    def update_capital(self, pnl: float) -> None:
        self.state.capital += pnl
        if self.state.capital > self.state.peak_capital:
            self.state.peak_capital = self.state.capital

    def reset_daily(self) -> None:
        self.state.daily_start = self.state.capital

    def get_summary(self) -> dict:
        return {
            "capital":      self.state.capital,
            "peak_capital": self.state.peak_capital,
            "drawdown":     self.state.drawdown,
            "daily_loss":   self.state.daily_loss,
            "return_pct":   (self.state.capital / self.cfg.initial_capital - 1),
        }

    def _portfolio_check(self) -> bool:
        if self.state.drawdown >= self.cfg.max_drawdown_pct:
            logger.warning(f"最大DD超過: {self.state.drawdown:.2%}")
            return False
        if self.state.daily_loss >= self.cfg.daily_loss_limit:
            logger.warning(f"日次損失上限: {self.state.daily_loss:.2%}")
            return False
        return True
