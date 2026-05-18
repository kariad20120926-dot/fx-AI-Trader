"""
src/strategies/backtester.py — ベクトル化バックテストエンジン
シグナル DataFrame を受け取り、取引履歴・パフォーマンス指標を計算する
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from strategies.risk_manager import RiskConfig
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Trade:
    """1取引の記録"""
    entry_time:   pd.Timestamp
    exit_time:    pd.Timestamp
    direction:    int           # 1=BUY, -1=SELL
    entry_price:  float
    exit_price:   float
    stop_loss:    float
    take_profit:  float
    lot_size:     float
    pnl:          float         # 損益（円）
    pnl_pips:     float         # 損益（pips）
    exit_reason:  str           # "tp" / "sl" / "signal" / "end"
    confidence:   float = 0.0


@dataclass
class BacktestResult:
    """バックテスト結果の集計"""
    # 基本統計
    total_trades:    int
    win_trades:      int
    lose_trades:     int
    win_rate:        float
    # 損益
    total_pnl:       float
    avg_pnl:         float
    avg_win:         float
    avg_loss:        float
    profit_factor:   float
    # リスク指標
    max_drawdown:    float
    max_drawdown_pct: float
    sharpe_ratio:    float
    sortino_ratio:   float
    calmar_ratio:    float
    # 詳細データ
    trades:          list[Trade] = field(default_factory=list)
    equity_curve:    Optional[pd.Series] = None
    monthly_returns: Optional[pd.Series] = None


class Backtester:
    """
    ベクトル化バックテストエンジン。

    入力:
      - OHLCV DataFrame（index=DatetimeIndex）
      - シグナル DataFrame（direction, confidence 列）

    特徴:
      - SL/TP ヒット判定（同じバー内での高値・安値を考慮）
      - スプレッド・手数料コストの反映
      - エクイティカーブ・月次リターンの計算
      - シャープ・ソルティーノ・カルマーレシオ
    """

    ANNUAL_FACTOR = {
        "M1": 252 * 24 * 60, "M5": 252 * 24 * 12,
        "M15": 252 * 24 * 4,  "H1": 252 * 24,
        "H4": 252 * 6,         "D":  252,
    }

    def __init__(
        self,
        initial_capital: float = 1_000_000.0,
        risk_config:     Optional[RiskConfig] = None,
        granularity:     str   = "H1",
    ):
        self.initial_capital = initial_capital
        self.cfg             = risk_config or RiskConfig(initial_capital=initial_capital)
        self.granularity     = granularity
        self._annual         = self.ANNUAL_FACTOR.get(granularity, 252 * 24)

    # ─────────────────────────────────────────────────────────────────────────

    def run(
        self,
        ohlcv:   pd.DataFrame,
        signals: pd.DataFrame,
        atr_col: str = "atr_14",
    ) -> BacktestResult:
        """
        バックテストを実行する。

        Parameters
        ----------
        ohlcv   : OHLCV + 特徴量 DataFrame
        signals : direction, confidence 列を含む DataFrame（ohlcv と同一インデックス）
        atr_col : ATR 列名（SL/TP計算に使用）
        """
        logger.info(f"バックテスト開始: {len(ohlcv)}本 / 資金={self.initial_capital:,.0f}円")

        capital  = self.initial_capital
        trades:  list[Trade] = []
        equity:  list[float] = [capital]
        eq_idx:  list[pd.Timestamp] = [ohlcv.index[0]]

        # 現在のオープンポジション（1ポジションのみ想定）
        position: Optional[dict] = None

        for i, (ts, row) in enumerate(ohlcv.iterrows()):
            sig = signals.loc[ts] if ts in signals.index else None

            # ── オープンポジションの SL/TP チェック ─────────────────────────
            if position is not None:
                closed, trade = self._check_exit(position, row, ts)
                if closed:
                    capital += trade.pnl
                    trades.append(trade)
                    position = None
                    equity.append(capital)
                    eq_idx.append(ts)

            # ── 新規エントリー判定 ────────────────────────────────────────────
            if position is None and sig is not None:
                direction = int(sig["direction"])
                confidence = float(sig.get("confidence", 0.5))

                if direction != 0:
                    atr = float(row.get(atr_col, row["high"] - row["low"]))
                    entry_price = float(row["close"]) + (
                        self.cfg.spread_pips * self.cfg.pip_value * direction
                    )
                    sl_dist = atr * self.cfg.sl_atr_mult
                    tp_dist = atr * self.cfg.tp_atr_mult

                    sl = entry_price - direction * sl_dist
                    tp = entry_price + direction * tp_dist

                    # ポジションサイズ計算
                    risk_amt = capital * self.cfg.risk_per_trade
                    risk_per_unit = sl_dist
                    lot = max(1, int(risk_amt / (risk_per_unit * self.cfg.lot_size + 1e-10)))
                    lot = min(lot, int(capital * self.cfg.max_position_pct / (entry_price * self.cfg.lot_size + 1e-10)))
                    lot = max(lot, 1)

                    # 手数料コスト
                    commission = entry_price * lot * self.cfg.lot_size * self.cfg.commission_pct
                    capital -= commission

                    position = {
                        "entry_time":  ts,
                        "direction":   direction,
                        "entry_price": entry_price,
                        "stop_loss":   sl,
                        "take_profit": tp,
                        "lot_size":    lot * self.cfg.lot_size,
                        "confidence":  confidence,
                    }

        # ── 最終バーで強制クローズ ─────────────────────────────────────────────
        if position is not None:
            last_row = ohlcv.iloc[-1]
            last_ts  = ohlcv.index[-1]
            exit_price = float(last_row["close"])
            pnl = (exit_price - position["entry_price"]) * position["direction"] * position["lot_size"]
            trades.append(Trade(
                entry_time=position["entry_time"],
                exit_time=last_ts,
                direction=position["direction"],
                entry_price=position["entry_price"],
                exit_price=exit_price,
                stop_loss=position["stop_loss"],
                take_profit=position["take_profit"],
                lot_size=position["lot_size"],
                pnl=pnl,
                pnl_pips=(exit_price - position["entry_price"]) * position["direction"] / self.cfg.pip_value,
                exit_reason="end",
                confidence=position["confidence"],
            ))
            capital += pnl
            equity.append(capital)
            eq_idx.append(last_ts)

        equity_series = pd.Series(equity, index=eq_idx)
        result = self._compute_metrics(trades, equity_series)
        self._print_summary(result)
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # プライベートメソッド
    # ─────────────────────────────────────────────────────────────────────────

    def _check_exit(
        self,
        pos: dict,
        row: pd.Series,
        ts:  pd.Timestamp,
    ) -> tuple[bool, Optional[Trade]]:
        """
        同バー内での SL/TP ヒット判定。
        陰線/陽線に関わらず high/low で判定する。
        """
        d  = pos["direction"]
        sl = pos["stop_loss"]
        tp = pos["take_profit"]
        hi = float(row["high"])
        lo = float(row["low"])

        exit_price  = None
        exit_reason = None

        if d == 1:    # ロング
            if lo <= sl:
                exit_price, exit_reason = sl, "sl"
            elif hi >= tp:
                exit_price, exit_reason = tp, "tp"
        else:          # ショート
            if hi >= sl:
                exit_price, exit_reason = sl, "sl"
            elif lo <= tp:
                exit_price, exit_reason = tp, "tp"

        if exit_price is None:
            return False, None

        pnl = (exit_price - pos["entry_price"]) * d * pos["lot_size"]
        pnl_pips = (exit_price - pos["entry_price"]) * d / self.cfg.pip_value
        trade = Trade(
            entry_time=pos["entry_time"],
            exit_time=ts,
            direction=d,
            entry_price=pos["entry_price"],
            exit_price=exit_price,
            stop_loss=sl,
            take_profit=tp,
            lot_size=pos["lot_size"],
            pnl=pnl,
            pnl_pips=pnl_pips,
            exit_reason=exit_reason,
            confidence=pos.get("confidence", 0.0),
        )
        return True, trade

    def _compute_metrics(
        self,
        trades: list[Trade],
        equity: pd.Series,
    ) -> BacktestResult:
        if not trades:
            return BacktestResult(
                total_trades=0, win_trades=0, lose_trades=0, win_rate=0,
                total_pnl=0, avg_pnl=0, avg_win=0, avg_loss=0,
                profit_factor=0, max_drawdown=0, max_drawdown_pct=0,
                sharpe_ratio=0, sortino_ratio=0, calmar_ratio=0,
            )

        pnls    = np.array([t.pnl for t in trades])
        wins    = pnls[pnls > 0]
        losses  = pnls[pnls < 0]

        # エクイティカーブからのドローダウン
        eq = equity.values
        peak = np.maximum.accumulate(eq)
        dd   = peak - eq
        dd_pct = dd / (peak + 1e-10)

        # リターン系列（日次換算）
        returns = equity.pct_change().dropna()
        rf      = 0.0   # リスクフリーレート
        excess  = returns - rf / self._annual

        sharpe  = float(excess.mean() / (excess.std() + 1e-10) * np.sqrt(self._annual))
        downside = returns[returns < 0].std()
        sortino = float(excess.mean() / (downside + 1e-10) * np.sqrt(self._annual))
        ann_ret = float((eq[-1] / eq[0]) ** (self._annual / max(len(eq), 1)) - 1)
        calmar  = float(ann_ret / (dd_pct.max() + 1e-10))

        # 月次リターン
        monthly = equity.resample("ME").last().pct_change().dropna()

        return BacktestResult(
            total_trades=len(trades),
            win_trades=len(wins),
            lose_trades=len(losses),
            win_rate=len(wins) / (len(trades) + 1e-10),
            total_pnl=float(pnls.sum()),
            avg_pnl=float(pnls.mean()),
            avg_win=float(wins.mean()) if len(wins) else 0.0,
            avg_loss=float(losses.mean()) if len(losses) else 0.0,
            profit_factor=float(wins.sum() / (-losses.sum() + 1e-10)) if len(losses) else float("inf"),
            max_drawdown=float(dd.max()),
            max_drawdown_pct=float(dd_pct.max()),
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            trades=trades,
            equity_curve=equity,
            monthly_returns=monthly,
        )

    def _print_summary(self, r: BacktestResult) -> None:
        logger.info(
            f"\n{'='*55}\n"
            f"{'バックテスト結果':^55}\n"
            f"{'='*55}\n"
            f"  取引数        : {r.total_trades:>8}\n"
            f"  勝率          : {r.win_rate:>8.2%}\n"
            f"  総損益        : ¥{r.total_pnl:>12,.0f}\n"
            f"  プロフィットF  : {r.profit_factor:>8.2f}\n"
            f"  最大DD        : {r.max_drawdown_pct:>8.2%}\n"
            f"  シャープレシオ : {r.sharpe_ratio:>8.2f}\n"
            f"  ソルティーノ  : {r.sortino_ratio:>8.2f}\n"
            f"  カルマー      : {r.calmar_ratio:>8.2f}\n"
            f"{'='*55}"
        )
