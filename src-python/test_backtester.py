# -*- coding: utf-8 -*-
"""バックテストエンジンの決定論的検証（合成データで手計算と照合）"""
import numpy as np
import pandas as pd

from strategies.backtester import Backtester
from strategies.risk_manager import RiskConfig, pip_size_for


def make_df(bars, start="2024-01-01"):
    idx = pd.date_range(start, periods=len(bars), freq="1h", tz="UTC")
    return pd.DataFrame(bars, columns=["open", "high", "low", "close"], index=idx).assign(
        volume=0.0, atr_14=0.5
    )


def make_signals(df, directions):
    return pd.DataFrame(
        {"direction": directions, "confidence": [0.9] * len(df)}, index=df.index
    )


def cfg(**kw):
    base = dict(
        initial_capital=1_000_000, risk_per_trade=0.02, spread_pips=0.4,
        slippage_pips=0.1, commission_pct=0.0, pip_value=0.01,
        lot_size=1000, leverage=25.0, max_position_pct=0.10,
        sl_atr_mult=2.0, tp_atr_mult=3.0,
    )
    base.update(kw)
    return RiskConfig(**base)


def approx(a, b, tol=1e-9):
    assert abs(a - b) < tol, f"expected {b}, got {a}"


# ── テスト1: 次バー始値エントリー + TP決済（ロング） ─────────────────────────
# シグナル: バー0。エントリーはバー1の始値 150.00 + 半スプレッド0.002 + 滑り0.001
# ATR=0.5 → SL=entry-1.0, TP=entry+1.5
bars = [
    [150.00, 150.10, 149.90, 150.00],   # シグナルバー
    [150.00, 150.20, 149.95, 150.10],   # エントリーバー(TP/SL未達)
    [150.10, 152.00, 150.05, 151.80],   # TPヒット
    [151.80, 151.90, 151.70, 151.80],
]
df = make_df(bars)
sigs = make_signals(df, [1, 0, 0, 0])
bt = Backtester(1_000_000, cfg(), "H1")
r = bt.run(df, sigs)

assert r.total_trades == 1, r.total_trades
t = r.trades[0]
entry_exp = 150.00 + 0.002 + 0.001          # ask + slippage
tp_exp    = entry_exp + 1.5
approx(t.entry_price, entry_exp)
assert t.exit_reason == "tp", t.exit_reason
approx(t.exit_price, tp_exp)                 # bid高値152-0.002=151.998 >= tp
assert t.entry_time == df.index[1], "エントリーは次バーであるべき"
# ロット: リスク2万円 / (SL距離1.0×1000) = 20ロット → 証拠金上限 10万×25/150.003≒16ロット
assert t.lot_size == 16_000, t.lot_size
approx(t.pnl, 1.5 * 16_000)
assert len(r.equity_curve) == len(df), "エクイティは全バー記録"
print("test1 OK: 次バー始値エントリー / TP決済 / 証拠金上限ロット")

# ── テスト2: ギャップでSLを飛び越え → 始値約定（ロング） ─────────────────────
bars = [
    [150.00, 150.10, 149.90, 150.00],   # シグナル
    [150.00, 150.20, 149.95, 150.10],   # エントリー (entry=150.003, SL=149.003)
    [148.00, 148.20, 147.90, 148.10],   # 窓開け: 始値148 << SL
]
df = make_df(bars)
sigs = make_signals(df, [1, 0, 0])
r = Backtester(1_000_000, cfg(), "H1").run(df, sigs)
t = r.trades[0]
assert t.exit_reason == "sl"
# bid始値 148-0.002=147.998 < SL → 始値約定 - 滑り0.001
approx(t.exit_price, 147.998 - 0.001)
print("test2 OK: ギャップ時はSL価格でなく始値で約定")

# ── テスト3: ショートのTP + bid/ask対称性 ───────────────────────────────────
bars = [
    [150.00, 150.10, 149.90, 150.00],   # シグナル(SELL)
    [150.00, 150.05, 149.90, 149.95],   # エントリー bid=149.998
    [149.95, 150.00, 148.00, 148.20],   # TPヒット (tp=entry-1.5)
]
df = make_df(bars)
sigs = make_signals(df, [-1, 0, 0])
r = Backtester(1_000_000, cfg(), "H1").run(df, sigs)
t = r.trades[0]
entry_exp = 150.00 - 0.002 - 0.001
approx(t.entry_price, entry_exp)
assert t.exit_reason == "tp"
approx(t.exit_price, entry_exp - 1.5)        # ask安値148.002 <= tp
print("test3 OK: ショートはbidエントリー/askで決済")

# ── テスト4: 反対シグナルで決済(signal) → 次バーでドテン ─────────────────────
bars = [
    [150.00, 150.10, 149.90, 150.00],   # BUYシグナル
    [150.00, 150.10, 149.90, 150.05],   # ロングエントリー
    [150.05, 150.15, 149.95, 150.00],   # SELLシグナル → 終値で決済
    [150.00, 150.10, 149.00, 149.10],   # ショートエントリー → 最終バーで強制クローズ
]
df = make_df(bars)
sigs = make_signals(df, [1, 0, -1, 0])
r = Backtester(1_000_000, cfg(), "H1").run(df, sigs)
assert r.total_trades == 2, r.total_trades
assert r.trades[0].exit_reason == "signal"
approx(r.trades[0].exit_price, 150.00 - 0.002)   # 終値bid
assert r.trades[1].direction == -1
assert r.trades[1].entry_time == df.index[3]
assert r.trades[1].exit_reason == "end"
print("test4 OK: 反対シグナル決済とドテン")

# ── テスト5: 資金不足ならエントリーしない（旧版は強制1ロット） ────────────────
r = Backtester(10_000, cfg(initial_capital=10_000), "H1").run(
    make_df([[150.0, 150.1, 149.9, 150.0]] * 5),
    make_signals(make_df([[150.0, 150.1, 149.9, 150.0]] * 5), [1, 0, 0, 0, 0]),
)
assert r.total_trades == 0, "1万円では証拠金不足のためノートレードであるべき"
print("test5 OK: 資金不足時はエントリー見送り")

# ── テスト6: 手数料が取引損益に反映される ──────────────────────────────────
bars = [
    [150.00, 150.10, 149.90, 150.00],
    [150.00, 150.20, 149.95, 150.10],
    [150.10, 152.00, 150.05, 151.80],
]
df = make_df(bars)
sigs = make_signals(df, [1, 0, 0])
r = Backtester(1_000_000, cfg(commission_pct=0.0002), "H1").run(df, sigs)
t = r.trades[0]
comm_exp = (t.entry_price + t.exit_price) * t.lot_size * 0.0002
approx(t.commission, comm_exp, 1e-6)
approx(t.pnl, 1.5 * t.lot_size - comm_exp, 1e-6)
print("test6 OK: 往復手数料がPnLに含まれる")

# ── テスト7: pip幅ヘルパー ───────────────────────────────────────────────────
approx(pip_size_for("USD_JPY"), 0.01)
approx(pip_size_for("EUR_USD"), 0.0001)
approx(pip_size_for("GBP_JPY"), 0.01)
print("test7 OK: 通貨ペア別pip幅")

# ── テスト8: 指標が有限値で、含み損がDDに反映される ─────────────────────────
np.random.seed(0)
n = 500
price = 150 + np.cumsum(np.random.randn(n) * 0.1)
bars = [[p, p + 0.15, p - 0.15, p + np.random.randn() * 0.05] for p in price]
df = make_df(bars)
dirs = np.random.choice([0, 0, 0, 1, -1], size=n)
r = Backtester(1_000_000, cfg(), "H1").run(df, make_signals(df, dirs))
assert np.isfinite(r.sharpe_ratio) and np.isfinite(r.sortino_ratio)
assert 0 <= r.max_drawdown_pct < 1
assert len(r.equity_curve) == n
print(f"test8 OK: ランダム500本 trades={r.total_trades} sharpe={r.sharpe_ratio:.2f} maxDD={r.max_drawdown_pct:.2%}")

# ── テスト9: 最大保有バー数で時間切れ決済 ───────────────────────────────────
bars = [[150.0, 150.1, 149.9, 150.0]] * 8
df = make_df(bars)
sigs = make_signals(df, [1, 0, 0, 0, 0, 0, 0, 0])
r = Backtester(1_000_000, cfg(max_hold_bars=3), "H1").run(df, sigs)
t = r.trades[0]
assert t.exit_reason == "time", t.exit_reason
# バー1でエントリー、保有3バー目（バー3）の終値で決済
assert t.exit_time == df.index[3], t.exit_time
print("test9 OK: 時間切れ決済")

# ── テスト10: ブレークイーブン移動（+1R到達後の反落は建値で守られる） ───────
bars = [
    [150.00, 150.10, 149.90, 150.00],   # シグナル
    [150.00, 150.10, 149.95, 150.05],   # エントリー(150.003) SL=149.003
    [150.05, 151.20, 150.00, 151.00],   # +1R超え → バー確定後 SL→建値
    [150.30, 150.40, 149.50, 149.60],   # 反落 → 建値SLヒット
]
df = make_df(bars)
sigs = make_signals(df, [1, 0, 0, 0])
r = Backtester(1_000_000, cfg(breakeven_rr=1.0, tp_atr_mult=10.0), "H1").run(df, sigs)
t = r.trades[0]
assert t.exit_reason == "sl"
approx(t.exit_price, 150.003 - 0.001)        # 建値SL - スリッページ
assert abs(t.pnl) < 100, f"建値決済なので損益はほぼゼロのはず: {t.pnl}"
print("test10 OK: ブレークイーブン移動")

# ── テスト11: トレーリングストップで利益確保 ────────────────────────────────
bars = [
    [150.00, 150.10, 149.90, 150.00],   # シグナル
    [150.00, 150.10, 149.95, 150.05],   # エントリー(150.003) SL=149.003
    [150.05, 152.00, 150.00, 151.90],   # 高値152 → SL = 151.998-1.0 = 150.998
    [151.80, 151.85, 150.50, 150.60],   # 押し目で トレールSL ヒット
]
df = make_df(bars)
sigs = make_signals(df, [1, 0, 0, 0])
r = Backtester(1_000_000, cfg(trailing_atr_mult=2.0, tp_atr_mult=10.0), "H1").run(df, sigs)
t = r.trades[0]
assert t.exit_reason == "sl"
approx(t.exit_price, 150.998 - 0.001)
assert t.pnl > 0, f"トレーリングで利益が残るはず: {t.pnl}"
print("test11 OK: トレーリングストップ")

# ── テスト12: トリプルバリアラベル（TPがSLより先なら1） ─────────────────────
import sys
sys.path.insert(0, ".")
from data.preprocessor import Preprocessor

n12 = 10
bars = [[150.0, 150.1, 149.9, 150.0] for _ in range(n12)]
bars[5] = [150.0, 151.6, 149.9, 150.0]   # バー5で+1.6の上ヒゲ（TP=+1.5を超える）
df12 = make_df(bars)
df12["atr_14"] = 0.5
labels = Preprocessor().create_labels_triple_barrier(df12, horizon=24, sl_mult=2.0, tp_mult=3.0)
assert (labels.iloc[0:5] == 1).all(), f"バー0-4はBUY勝ちのはず: {labels.tolist()}"
assert (labels.iloc[5:] == 0).all(),  f"バー5以降はHOLDのはず: {labels.tolist()}"
print("test12 OK: トリプルバリアラベル")

# ── テスト13: 経済指標ブラックアウト判定（ネットワーク不要・注入イベント） ──
from datetime import datetime, timedelta, timezone
from data.economic_calendar import EconomicCalendar

now = datetime.now(timezone.utc)
cal = EconomicCalendar(blackout_before_min=30, blackout_after_min=30, min_impact="High")
cal._loaded_at = now   # refresh() の再取得を抑止
cal._events = [
    {"time": now + timedelta(minutes=10), "country": "USD", "title": "CPI y/y",
     "impact": "High", "rank": 3, "forecast": "", "previous": ""},
    {"time": now + timedelta(minutes=10), "country": "GBP", "title": "BOE Rate",
     "impact": "High", "rank": 3, "forecast": "", "previous": ""},
    {"time": now - timedelta(minutes=60), "country": "JPY", "title": "BOJ",
     "impact": "High", "rank": 3, "forecast": "", "previous": ""},
]
blk, ev = cal.is_blackout("USD_JPY")
assert blk and "CPI" in ev, (blk, ev)
blk, _ = cal.is_blackout("EUR_CHF")
assert not blk, "EUR_CHFはUSD/GBP/JPYイベントの影響を受けない"
blk, _ = cal.is_blackout("USD_JPY", at=now - timedelta(hours=3))
assert not blk, "3時間前はブラックアウト外"
up = cal.upcoming("GBP_USD", within_hours=24)
assert len(up) == 2, f"GBP_USDはCPIとBOEの2件: {len(up)}"
print("test13 OK: 経済指標ブラックアウト判定")

print("\n全テスト合格")
