# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional
import pandas as pd
from utils.logger import get_logger
from utils.ssl_trust import ensure_truststore

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

CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


class YahooClient:
    """
    Yahoo Finance クライアント。

    取得経路:
      1. chart API 直接（requests + OS証明書ストア）… プロキシ環境でも動作
      2. yfinance … フォールバック
    """

    def fetch_candles(
        self,
        instrument:  str = "USD_JPY",
        granularity: str = "H1",
        count:       int = 500,
    ) -> pd.DataFrame:
        symbol   = SYMBOL_MAP.get(instrument, instrument)
        interval = INTERVAL_MAP.get(granularity, "1h")
        period   = PERIOD_MAP.get(interval, "730d")

        try:
            df = self._fetch_direct(symbol, interval, period)
            source = "chart API"
        except Exception as e:
            logger.warning(f"chart API 取得失敗({e})、yfinance にフォールバック")
            df = self._fetch_yfinance(symbol, interval, period)
            source = "yfinance"

        if df.empty:
            raise ValueError(f"データが取得できませんでした: {symbol}")

        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")

        df.index.name = "time"
        df.index      = pd.DatetimeIndex(df.index)
        df            = df.dropna()

        if len(df) > count:
            df = df.tail(count)

        logger.info(f"取得完了({source}): {len(df)}本 ({df.index[0]} ~ {df.index[-1]})")
        return df

    # ─────────────────────────────────────────────────────────────────────────

    def _fetch_direct(self, symbol: str, interval: str, period: str) -> pd.DataFrame:
        """Yahoo chart API を直接叩く（yfinance/curl_cffi 非依存）"""
        ensure_truststore()
        import requests

        logger.info(f"Yahoo chart API からデータ取得: {symbol} {interval} range={period}")
        resp = requests.get(
            CHART_API.format(symbol=symbol),
            params={"range": period, "interval": interval},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()["chart"]["result"][0]

        ts    = result["timestamp"]
        quote = result["indicators"]["quote"][0]
        df = pd.DataFrame(
            {
                "open":   quote["open"],
                "high":   quote["high"],
                "low":    quote["low"],
                "close":  quote["close"],
                "volume": quote.get("volume") or [0] * len(ts),
            },
            index=pd.to_datetime(ts, unit="s", utc=True),
        )
        return df.dropna(subset=["open", "high", "low", "close"])

    def _fetch_yfinance(self, symbol: str, interval: str, period: str) -> pd.DataFrame:
        try:
            import yfinance as yf
        except ImportError:
            raise ImportError("pip install yfinance")

        logger.info(f"yfinance からデータ取得: {symbol} {interval} period={period}")
        ticker = yf.Ticker(symbol)
        df     = ticker.history(period=period, interval=interval, auto_adjust=True)
        if df.empty:
            return df
        df.columns = [c.lower() for c in df.columns]
        cols       = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
        return df[cols].copy()
