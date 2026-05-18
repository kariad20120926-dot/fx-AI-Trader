# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional
import pandas as pd
from utils.logger import get_logger

logger = get_logger(__name__)

SYMBOL_MAP = {
    "USD_JPY": "USDJPY=X",
    "EUR_USD": "EURUSD=X",
    "GBP_USD": "GBPUSD=X",
    "EUR_JPY": "EURJPY=X",
    "AUD_USD": "AUDUSD=X",
    "USD_CHF": "USDCHF=X",
}

INTERVAL_MAP = {
    "M1": "1m", "M5": "5m", "M15": "15m",
    "H1": "1h", "H4": "4h", "D": "1d",
    "W": "1wk", "MN": "1mo",
}

PERIOD_MAP = {
    "1m": "7d", "5m": "60d", "15m": "60d",
    "1h": "730d", "4h": "730d", "1d": "5y",
    "1wk": "10y", "1mo": "max",
}


class YahooClient:

    def fetch_candles(
        self,
        instrument:  str = "USD_JPY",
        granularity: str = "H1",
        count:       int = 500,
    ) -> pd.DataFrame:
        try:
            import yfinance as yf
        except ImportError:
            raise ImportError("pip install yfinance")

        symbol   = SYMBOL_MAP.get(instrument, instrument)
        interval = INTERVAL_MAP.get(granularity, "1h")
        period   = PERIOD_MAP.get(interval, "730d")

        logger.info(f"Yahoo Finance からデータ取得: {symbol} {interval} period={period}")

        ticker = yf.Ticker(symbol)
        df     = ticker.history(period=period, interval=interval, auto_adjust=True)

        if df.empty:
            raise ValueError(f"データが取得できませんでした: {symbol}")

        df.columns    = [c.lower() for c in df.columns]
        cols          = [c for c in ["open","high","low","close","volume"] if c in df.columns]
        df            = df[cols].copy()

        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")

        df.index.name = "time"
        df.index      = pd.DatetimeIndex(df.index)
        df            = df.dropna()

        # count 本に絞る（上限なし）
        if len(df) > count:
            df = df.tail(count)

        logger.info(f"取得完了: {len(df)}本 ({df.index[0]} ~ {df.index[-1]})")
        return df
