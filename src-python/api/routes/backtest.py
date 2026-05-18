# -*- coding: utf-8 -*-
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import asyncio, json

router = APIRouter()


class BacktestRequest(BaseModel):
    instrument:      str   = "USD_JPY"
    granularity:     str   = "H1"
    candle_count:    int   = Field(2000, ge=100, le=10000)
    initial_capital: float = 1_000_000.0
    risk_per_trade:  float = Field(0.02, ge=0.005, le=0.10)
    sl_atr_mult:     float = 2.0
    tp_atr_mult:     float = 3.0
    confidence_min:  float = Field(0.33, ge=0.0, le=1.0)
    adx_min:         float = Field(0.0,  ge=0.0, le=50.0)


async def _run_backtest_stream(req: BacktestRequest):
    def send(msg: str, pct: int, data: dict = None):
        payload = {"message": msg, "progress": pct}
        if data:
            payload["result"] = data
        return f"data: {json.dumps(payload)}\n\n"

    yield send("データを取得中...", 10)
    await asyncio.sleep(0.1)

    try:
        from data.pipeline import DataPipeline, PipelineConfig
        from models.ensemble import EnsembleModel
        from strategies.signal_generator import SignalGenerator
        from strategies.backtester import Backtester
        from strategies.risk_manager import RiskConfig
        from pathlib import Path

        model_path = Path(f"models/saved/{req.instrument}/{req.granularity}")
        if not model_path.exists():
            yield send("モデルが見つかりません。モデル管理で学習してください。", 100,
                       {"error": "model not found"})
            return

        model = EnsembleModel()
        model.load(model_path)

        yield send("Yahoo Finance からデータ取得中...", 25)
        await asyncio.sleep(0.1)

        try:
            cfg_raw = PipelineConfig(
                source="yahoo",
                instrument=req.instrument,
                granularity=req.granularity,
                candle_count=req.candle_count,
                drop_ohlcv=False,
            )
            bundle_raw  = DataPipeline(cfg_raw).run()
            data_source = "Yahoo Finance"
        except Exception as e:
            yield send(f"Yahoo取得失敗。ダミーデータで実行...", 25)
            cfg_raw = PipelineConfig(
                source="dummy",
                instrument=req.instrument,
                granularity=req.granularity,
                candle_count=req.candle_count,
                drop_ohlcv=False,
            )
            bundle_raw  = DataPipeline(cfg_raw).run()
            data_source = "ダミーデータ"

        ohlcv_cols  = ["open", "high", "low", "close", "volume"]
        X_test_feat = bundle_raw.X_test.drop(
            columns=[c for c in ohlcv_cols if c in bundle_raw.X_test.columns]
        )

        yield send(f"シグナル生成中... ({data_source})", 55)
        await asyncio.sleep(0.1)

        sg = SignalGenerator(
            model=model,
            confidence_min=req.confidence_min,
            adx_min=req.adx_min,
        )
        sg.fit_thresholds(X_test_feat)
        signals = sg.generate(X_test_feat)

        yield send("バックテスト実行中...", 75)
        await asyncio.sleep(0.1)

        risk_cfg = RiskConfig(
            initial_capital=req.initial_capital,
            risk_per_trade=req.risk_per_trade,
            sl_atr_mult=req.sl_atr_mult,
            tp_atr_mult=req.tp_atr_mult,
        )
        bt = Backtester(
            initial_capital=req.initial_capital,
            risk_config=risk_cfg,
            granularity=req.granularity,
        )

        ohlcv_test = bundle_raw.raw.loc[bundle_raw.X_test.index]
        atr_adx    = bundle_raw.X_test[
            [c for c in ["atr_14", "adx"] if c in bundle_raw.X_test.columns]
        ].reindex(ohlcv_test.index)
        ohlcv_feat = ohlcv_test.join(atr_adx, how="left")
        result     = bt.run(ohlcv_feat, signals)

        monthly = {}
        if result.monthly_returns is not None:
            monthly = {
                str(k)[:7]: round(float(v), 4)
                for k, v in result.monthly_returns.items()
            }

        yield send("完了", 100, {
            "total_trades":     result.total_trades,
            "win_rate":         round(result.win_rate, 4),
            "total_pnl":        round(result.total_pnl, 2),
            "profit_factor":    round(result.profit_factor, 3),
            "max_drawdown_pct": round(result.max_drawdown_pct, 4),
            "sharpe_ratio":     round(result.sharpe_ratio, 3),
            "sortino_ratio":    round(result.sortino_ratio, 3),
            "monthly_returns":  monthly,
        })

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        yield send(f"Error: {e}", 100, {"error": str(e)})


@router.post("/run")
async def run_backtest(req: BacktestRequest):
    return StreamingResponse(
        _run_backtest_stream(req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
