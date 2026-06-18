"""
src/strategies/backtester.py — バックテストエンジン（高精度版）
シグナル DataFrame を受け取り、取引履歴・パフォーマンス指標を計算する

精度向上のための実装方針:
  - シグナル発生バーの「次バー始値」でエントリー（ルックアヘッド排除）
  - bid/ask スプレッドモデル（ロングは ask で買い bid で売る）
  - 成行・ストップ注文へのスリッページ適用（リミット=TP には適用しない）
  - 窓開け（ギャップ）対応: SL/TP を飛び越えて寄り付いた場合は始値で約定
  - 同一バー内で SL/TP 両方に届く場合は SL 優先（保守的仮定）
  - 手数料はエントリー/決済の両側で徴収し、取引損益に含める
  - 全バーで含み損益を時価評価したエクイティカーブ → 正確な DD・シャープ計算
  - 証拠金ベースのポジション上限（レバレッジ考慮）、資金不足時はエントリー見送り
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
    pnl:          float         # 損益（円、手数料込み）
    pnl_pips:     float         # 損益（pips）
    exit_reason:  str           # "tp" / "sl" / "signal" / "end"
    confidence:   float = 0.0
    commission:   float = 0.0   # 往復手数料


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
    バックテストエンジン。

    入力:
      - OHLCV DataFrame（index=DatetimeIndex）
      - シグナル DataFrame（direction, confidence 列）
    """

    # FXは24時間×約252営業日
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
        # スプレッドは bid/ask 差なので片側は半分
        self._half_spread    = self.cfg.spread_pips * self.cfg.pip_value / 2.0
        self._slip           = self.cfg.slippage_pips * self.cfg.pip_value

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
        equity:  list[float] = []
        skipped_funds = 0

        position: Optional[dict] = None   # 現在のオープンポジション（1つのみ）
        pending:  Optional[dict] = None   # 次バー始値で執行待ちのシグナル

        for ts, row in ohlcv.iterrows():
            o = float(row["open"])
            h = float(row["high"])
            l = float(row["low"])
            c = float(row["close"])

            # ── 1. 執行待ちシグナルを当バー始値でエントリー ──────────────────
            if pending is not None:
                if position is None:
                    position, ok = self._open_position(pending, o, ts, capital)
                    if not ok:
                        skipped_funds += 1
                pending = None

            # ── 2. オープンポジションの SL/TP チェック（当バー高安） ─────────
            if position is not None:
                hit = self._check_exit(position, o, h, l)
                if hit is not None:
                    exit_price, reason = hit
                    trade = self._close_position(position, exit_price, reason, ts)
                    capital += trade.pnl
                    trades.append(trade)
                    position = None
                else:
                    position["bars_held"] += 1
                    # 時間切れ決済（トリプルバリアの保有期限と整合させる用途）
                    if (
                        self.cfg.max_hold_bars > 0
                        and position["bars_held"] >= self.cfg.max_hold_bars
                    ):
                        exit_price = c - position["direction"] * self._half_spread
                        trade = self._close_position(position, exit_price, "time", ts)
                        capital += trade.pnl
                        trades.append(trade)
                        position = None
                    else:
                        # トレーリング/建値移動は当バーの値動き確定後に更新
                        # （次バー以降の判定に反映 = 未来参照なし）
                        self._update_stops(position, h, l)

            # ── 3. シグナル処理（執行は次バー始値） ──────────────────────────
            sig = signals.loc[ts] if ts in signals.index else None
            if sig is not None:
                direction  = int(sig["direction"])
                confidence = float(sig.get("confidence", 0.5))
                if direction != 0:
                    atr = float(row.get(atr_col, h - l))
                    if position is not None and direction == -position["direction"]:
                        # 反対シグナル: 当バー終値で決済し、次バーでドテン
                        exit_price = c - position["direction"] * self._half_spread
                        trade = self._close_position(position, exit_price, "signal", ts)
                        capital += trade.pnl
                        trades.append(trade)
                        position = None
                        pending = {"direction": direction, "confidence": confidence, "atr": atr}
                    elif position is None:
                        pending = {"direction": direction, "confidence": confidence, "atr": atr}

            # ── 4. バー終値で時価評価（含み損益込みエクイティ） ──────────────
            if position is not None:
                mid_exit   = c - position["direction"] * self._half_spread
                unrealized = (
                    (mid_exit - position["entry_price"])
                    * position["direction"] * position["lot_size"]
                    - position["entry_commission"]
                )
                equity.append(capital + unrealized)
            else:
                equity.append(capital)

        # ── 最終バーで強制クローズ ─────────────────────────────────────────────
        if position is not None:
            last_row   = ohlcv.iloc[-1]
            last_ts    = ohlcv.index[-1]
            exit_price = float(last_row["close"]) - position["direction"] * self._half_spread
            trade = self._close_position(position, exit_price, "end", last_ts)
            capital += trade.pnl
            trades.append(trade)
            equity[-1] = capital

        if skipped_funds:
            logger.info(f"資金不足/上限超過でエントリー見送り: {skipped_funds}回")

        equity_series = pd.Series(equity, index=ohlcv.index)
        result = self._compute_metrics(trades, equity_series)
        self._print_summary(result)
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # プライベートメソッド
    # ─────────────────────────────────────────────────────────────────────────

    def _open_position(
        self,
        sig:     dict,
        o:       float,
        ts:      pd.Timestamp,
        capital: float,
    ) -> tuple[Optional[dict], bool]:
        """次バー始値でのエントリー。資金不足なら (None, False)。"""
        direction = sig["direction"]
        atr       = sig["atr"]

        # ロングは ask（始値+半スプレッド）で買い、ショートは bid で売る
        entry_price = o + direction * (self._half_spread + self._slip)
        sl_dist = atr * self.cfg.sl_atr_mult
        tp_dist = atr * self.cfg.tp_atr_mult
        if sl_dist <= 0:
            return None, False

        sl = entry_price - direction * sl_dist
        tp = entry_price + direction * tp_dist

        # リスクベースのロット数（信頼度連動: RiskManager のライブ挙動と整合）
        risk_amt = capital * self.cfg.risk_per_trade
        if self.cfg.confidence_sizing:
            risk_amt *= 0.5 + 0.5 * min(sig["confidence"], 1.0)
        risk_per_lot = sl_dist * self.cfg.lot_size
        lots = int(risk_amt / (risk_per_lot + 1e-10))

        # 証拠金上限（必要証拠金 = 想定元本 / レバレッジ ≦ 資金 × max_position_pct）
        margin_budget = capital * self.cfg.max_position_pct
        max_units     = margin_budget * self.cfg.leverage / (entry_price + 1e-10)
        max_lots      = int(max_units / self.cfg.lot_size)
        lots = min(lots, max_lots)

        if lots < 1:
            return None, False

        units      = lots * self.cfg.lot_size
        commission = entry_price * units * self.cfg.commission_pct

        return {
            "entry_time":       ts,
            "direction":        direction,
            "entry_price":      entry_price,
            "stop_loss":        sl,
            "take_profit":      tp,
            "lot_size":         units,
            "confidence":       sig["confidence"],
            "entry_commission": commission,
            "atr":              atr,
            "sl_dist":          sl_dist,
            "best":             entry_price,   # 有利方向の極値（トレーリング用）
            "bars_held":        0,
        }, True

    def _update_stops(self, pos: dict, h: float, l: float) -> None:
        """
        当バーの高安確定後にトレーリングストップ・建値移動を適用する。
        SL は有利方向にのみ動かす（緩めない）。
        """
        d = pos["direction"]

        # 有利方向の極値を更新
        if d == 1:
            pos["best"] = max(pos["best"], h - self._half_spread)
        else:
            pos["best"] = min(pos["best"], l + self._half_spread)

        new_sl = pos["stop_loss"]

        # トレーリングストップ（シャンデリア方式: 極値から ATR×mult）
        if self.cfg.trailing_atr_mult > 0:
            trail = pos["best"] - d * pos["atr"] * self.cfg.trailing_atr_mult
            new_sl = max(new_sl, trail) if d == 1 else min(new_sl, trail)

        # ブレークイーブン移動（含み益が SL距離×rr に到達したら建値へ）
        if self.cfg.breakeven_rr > 0:
            progress = (pos["best"] - pos["entry_price"]) * d
            if progress >= pos["sl_dist"] * self.cfg.breakeven_rr:
                be = pos["entry_price"]
                new_sl = max(new_sl, be) if d == 1 else min(new_sl, be)

        pos["stop_loss"] = new_sl

    def _check_exit(
        self,
        pos: dict,
        o:   float,
        h:   float,
        l:   float,
    ) -> Optional[tuple[float, str]]:
        """
        同バー内での SL/TP ヒット判定。
          - 決済はロング=bid、ショート=ask で行う
          - ギャップで SL を飛び越えた場合は始値約定（不利方向）+ スリッページ
          - ギャップで TP を飛び越えた場合は始値約定（有利方向、リミット注文の挙動）
          - SL/TP 両方に届くバーは SL 優先（保守的）
        """
        d  = pos["direction"]
        sl = pos["stop_loss"]
        tp = pos["take_profit"]

        if d == 1:    # ロング → bid で決済
            bo, bh, bl = o - self._half_spread, h - self._half_spread, l - self._half_spread
            if bl <= sl:
                return min(sl, bo) - self._slip, "sl"
            if bh >= tp:
                return max(tp, bo), "tp"
        else:          # ショート → ask で決済
            ao, ah, al = o + self._half_spread, h + self._half_spread, l + self._half_spread
            if ah >= sl:
                return max(sl, ao) + self._slip, "sl"
            if al <= tp:
                return min(tp, ao), "tp"
        return None

    def _close_position(
        self,
        pos:        dict,
        exit_price: float,
        reason:     str,
        ts:         pd.Timestamp,
    ) -> Trade:
        d     = pos["direction"]
        units = pos["lot_size"]
        exit_commission  = exit_price * units * self.cfg.commission_pct
        total_commission = pos["entry_commission"] + exit_commission
        gross = (exit_price - pos["entry_price"]) * d * units
        pnl   = gross - total_commission
        return Trade(
            entry_time=pos["entry_time"],
            exit_time=ts,
            direction=d,
            entry_price=pos["entry_price"],
            exit_price=exit_price,
            stop_loss=pos["stop_loss"],
            take_profit=pos["take_profit"],
            lot_size=units,
            pnl=pnl,
            pnl_pips=(exit_price - pos["entry_price"]) * d / self.cfg.pip_value,
            exit_reason=reason,
            confidence=pos.get("confidence", 0.0),
            commission=total_commission,
        )

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
                equity_curve=equity,
            )

        pnls    = np.array([t.pnl for t in trades])
        wins    = pnls[pnls > 0]
        losses  = pnls[pnls < 0]

        # 時価評価エクイティカーブからのドローダウン（含み損も反映）
        eq = equity.values
        peak = np.maximum.accumulate(eq)
        dd   = peak - eq
        dd_pct = dd / (peak + 1e-10)

        # バー単位リターン → 年率換算（エクイティはバー毎に記録済み）
        returns = equity.pct_change().dropna()
        sharpe  = float(returns.mean() / (returns.std(ddof=0) + 1e-10) * np.sqrt(self._annual))
        # ソルティーノ: 下方偏差 = sqrt(mean(min(r,0)^2))
        downside = float(np.sqrt(np.mean(np.minimum(returns.values, 0.0) ** 2)))
        sortino  = float(returns.mean() / (downside + 1e-10) * np.sqrt(self._annual))
        n_bars   = max(len(equity), 2)
        ann_ret  = float((eq[-1] / eq[0]) ** (self._annual / n_bars) - 1) if eq[0] > 0 else 0.0
        calmar   = float(ann_ret / (dd_pct.max() + 1e-10))

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
