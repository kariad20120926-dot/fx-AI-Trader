# -*- coding: utf-8 -*-
"""
sweep_params.py — バックテストのパラメータ探索

データ取得とモデル確率計算を1回だけ行い、フィルター閾値とトレード管理
パラメータの組み合わせを高速に総当たりして PF・勝率・取引数を比較する。

使い方:
    python sweep_params.py --instrument USD_JPY --granularity H1 --count 5000
"""
from __future__ import annotations

import argparse
import itertools
from pathlib import Path

import numpy as np
import pandas as pd

from data.pipeline import DataPipeline, PipelineConfig
from models.ensemble import EnsembleModel
from strategies.signal_generator import SignalGenerator
from strategies.backtester import Backtester
from strategies.risk_manager import RiskConfig, pip_size_for
from utils.logger import get_logger

logger = get_logger(__name__)


class CachedModel:
    """事前計算した predict / predict_proba を返すダミーモデル（SignalGenerator用）"""
    def __init__(self, labels: np.ndarray, proba: np.ndarray):
        self._labels = labels
        self._proba  = proba

    def predict(self, X):        return self._labels
    def predict_proba(self, X):  return self._proba


def prepare(instrument: str, granularity: str, count: int):
    """データ・特徴量・モデル確率を一度だけ用意する"""
    model_path = Path(f"models/saved/{instrument}/{granularity}")
    if not model_path.exists():
        raise SystemExit(f"モデル未学習: {model_path}")

    model = EnsembleModel()
    model.load(model_path)

    bundle = DataPipeline(PipelineConfig(
        source="yahoo", instrument=instrument, granularity=granularity,
        candle_count=count, drop_ohlcv=False,
    )).run()

    ohlcv = ["open", "high", "low", "close", "volume"]
    X_test  = bundle.X_test.drop(columns=[c for c in ohlcv if c in bundle.X_test.columns])
    X_train = bundle.X_train.drop(columns=[c for c in ohlcv if c in bundle.X_train.columns])

    # モデル確率は1回だけ計算
    labels = model.predict(X_test)
    proba  = model.predict_proba(X_test)
    cached = CachedModel(labels, proba)

    ohlcv_test = bundle.raw.loc[bundle.X_test.index]
    atr_adx    = bundle.X_test[[c for c in ["atr_14", "adx"] if c in bundle.X_test.columns]] \
        .reindex(ohlcv_test.index)
    ohlcv_feat = ohlcv_test.join(atr_adx, how="left")

    conf = proba.max(axis=1)
    logger.info(f"確率分布: p50={np.percentile(conf,50):.3f} p75={np.percentile(conf,75):.3f} "
                f"p90={np.percentile(conf,90):.3f} max={conf.max():.3f}")

    return cached, X_train, X_test, ohlcv_feat, instrument, granularity


def run_one(cached, X_train, X_test, ohlcv_feat, instrument, granularity,
            conf_min, adx_min, trailing, breakeven, max_hold) -> dict:
    sg = SignalGenerator(model=cached, confidence_min=conf_min, adx_min=adx_min)
    sg.fit_thresholds(X_train)
    signals = sg.generate(X_test)

    risk = RiskConfig(
        initial_capital=1_000_000, risk_per_trade=0.02,
        sl_atr_mult=2.0, tp_atr_mult=3.0,
        spread_pips=0.3, slippage_pips=0.1,
        pip_value=pip_size_for(instrument),
        trailing_atr_mult=trailing, breakeven_rr=breakeven, max_hold_bars=max_hold,
    )
    r = Backtester(1_000_000, risk, granularity).run(ohlcv_feat, signals)
    return {
        "conf": conf_min, "adx": adx_min, "trail": trailing,
        "be": breakeven, "hold": max_hold,
        "trades": r.total_trades, "win": round(r.win_rate, 3),
        "pf": round(r.profit_factor, 3) if np.isfinite(r.profit_factor) else 99.0,
        "pnl": round(r.total_pnl, 0), "dd": round(r.max_drawdown_pct, 3),
        "sharpe": round(r.sharpe_ratio, 2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default="USD_JPY")
    ap.add_argument("--granularity", default="H1")
    ap.add_argument("--count", type=int, default=5000)
    args = ap.parse_args()

    prep = prepare(args.instrument, args.granularity, args.count)

    # 探索グリッド
    grid = {
        "conf_min":  [0.34, 0.36, 0.38, 0.40],
        "adx_min":   [0.0, 15.0, 20.0],
        "trailing":  [0.0, 2.0, 3.0],
        "breakeven": [0.0, 1.0],
        "max_hold":  [24, 48],
    }
    combos = list(itertools.product(*grid.values()))
    logger.info(f"探索開始: {len(combos)} 通り")

    rows = []
    for i, (cm, am, tr, be, mh) in enumerate(combos):
        # ログ抑制のためバックテスターのprintは内部INFO、ここでは結果のみ集計
        res = run_one(*prep, cm, am, tr, be, mh)
        rows.append(res)

    df = pd.DataFrame(rows)
    # 取引数が少なすぎる設定は除外（統計的に無意味）
    valid = df[df["trades"] >= 10].copy()
    valid = valid.sort_values(["pf", "sharpe"], ascending=False)

    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 40)

    print("\n========== 上位15設定 (取引数>=10, PF降順) ==========")
    print(valid.head(15).to_string(index=False))
    print("\n========== 全体統計 ==========")
    print(f"設定数={len(df)} / 有効(>=10取引)={len(valid)}")
    print(f"PF中央値={valid['pf'].median():.3f} 勝率中央値={valid['win'].median():.3f}")
    if len(valid):
        best = valid.iloc[0]
        print(f"\n最良: conf={best['conf']} adx={best['adx']} trail={best['trail']} "
              f"be={best['be']} hold={best['hold']} "
              f"→ PF={best['pf']} 勝率={best['win']} 取引={best['trades']} シャープ={best['sharpe']}")

    out = Path("sweep_result.csv")
    df.to_csv(out, index=False)
    print(f"\n全結果を保存: {out}")


if __name__ == "__main__":
    main()
