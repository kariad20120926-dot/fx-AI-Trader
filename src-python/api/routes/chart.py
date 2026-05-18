# -*- coding: utf-8 -*-
from fastapi import APIRouter, Query

router = APIRouter()

JST_OFFSET = 9 * 3600  # 9時間


def fetch_candle_data(instrument: str, granularity: str, count: int):
    from data.pipeline import get_twelvedata_key
    td_key = get_twelvedata_key()
    if td_key:
        try:
            from data.twelvedata_client import TwelveDataClient
            return TwelveDataClient(td_key).fetch_candles(
                instrument=instrument, granularity=granularity, count=count,
            )
        except Exception:
            pass
    from data.yahoo_client import YahooClient
    return YahooClient().fetch_candles(
        instrument=instrument, granularity=granularity, count=count,
    )


@router.get("/candles")
def get_candles(
    instrument:  str = Query("USD_JPY"),
    granularity: str = Query("H1"),
    count:       int = Query(300, ge=50, le=1000),
):
    try:
        df = fetch_candle_data(instrument, granularity, count)
        if df.empty:
            return {"candles": [], "stats": {}, "error": "no data"}

        candles = []
        for ts, row in df.iterrows():
            candles.append({
                "time":  int(ts.timestamp()),
                "open":  round(float(row["open"]),  5),
                "high":  round(float(row["high"]),  5),
                "low":   round(float(row["low"]),   5),
                "close": round(float(row["close"]), 5),
            })

        latest = float(df["close"].iloc[-1])
        prev   = float(df["close"].iloc[-2]) if len(df) > 1 else latest
        change = latest - prev
        pct    = (change / prev) * 100 if prev != 0 else 0

        return {
            "candles": candles,
            "stats": {
                "latest":     round(latest, 5),
                "change":     round(change, 5),
                "change_pct": round(pct, 3),
                "high":       round(float(df["high"].max()), 5),
                "low":        round(float(df["low"].min()),  5),
            }
        }
    except Exception as e:
        return {"candles": [], "stats": {}, "error": str(e)}
