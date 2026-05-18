# -*- coding: utf-8 -*-
"""
data/twelvedata_client.py — Twelve Data API クライアント
リアルタイム + 履歴 OHLCV データを取得する（無料プラン対応）
"""
from __future__ import annotations
import time
import requests
import pandas as pd
from utils.logger import get_logger

logger = get_logger(__name__)

# 通貨ペア変換マップ (OANDA形式 → Twelve Data形式)
SYMBOL_MAP = {
    "USD_JPY": "USD/JPY",
    "EUR_USD": "EUR/USD",
    "GBP_USD": "GBP/USD",
    "EUR_JPY": "EUR/JPY",
    "AUD_USD": "AUD/USD",
    "USD_CHF": "USD/CHF",
}

# 時間足変換マップ
INTERVAL_MAP = {
    "M1":  "1min",
    "M5":  "5min",
    "M15": "15min",
    "H1":  "1h",
    "H4":  "4h",
    "D":   "1day",
    "W":   "1week",
    "MN":  "1month",
}

BASE_URL = "https://api.twelvedata.com"


class TwelveDataClient:

    def __init__(self, api_key: str):
        self.api_key = api_key

    def fetch_candles(
        self,
        instrument:  str = "USD_JPY",
        granularity: str = "H1",
        count:       int = 500,
    ) -> pd.DataFrame:
        symbol   = SYMBOL_MAP.get(instrument, instrument)
        interval = INTERVAL_MAP.get(granularity, "1h")

        logger.info(f"Twelve Data からデータ取得: {symbol} {interval} count={count}")

        url    = f"{BASE_URL}/time_series"
        params = {
            "symbol":     symbol,
            "interval":   interval,
            "outputsize": min(count, 5000),
            "apikey":     self.api_key,
            "format":     "JSON",
            "order":      "ASC",
            "timezone":   "UTC",
        }

        res  = requests.get(url, params=params, timeout=15)
        data = res.json()

        if data.get("status") == "error":
            raise ValueError(f"Twelve Data エラー: {data.get('message')}")

        values = data.get("values", [])
        if not values:
            raise ValueError(f"データが取得できませんでした: {symbol}")

        rows = []
        for v in values:
            rows.append({
                "time":   pd.Timestamp(v["datetime"], tz="UTC"),
                "open":   float(v["open"]),
                "high":   float(v["high"]),
                "low":    float(v["low"]),
                "close":  float(v["close"]),
                "volume": float(v.get("volume", 0)),
            })

        df = pd.DataFrame(rows).set_index("time")
        df.index.name = "time"
        df = df.dropna()

        if len(df) > count:
            df = df.tail(count)

        logger.info(f"取得完了: {len(df)}本 ({df.index[0]} ~ {df.index[-1]})")
        return df

    def get_price(self, instrument: str = "USD_JPY") -> float:
        """現在値をリアルタイムで取得する"""
        symbol = SYMBOL_MAP.get(instrument, instrument)
        url    = f"{BASE_URL}/price"
        params = {"symbol": symbol, "apikey": self.api_key}
        res    = requests.get(url, params=params, timeout=10)
        data   = res.json()
        return float(data.get("price", 0))
