"""
src/data/oanda_client.py — OANDA REST API ラッパー
oandapyV20 を使って過去データ・リアルタイムレートを取得する
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import oandapyV20
import oandapyV20.endpoints.instruments as instruments
import oandapyV20.endpoints.orders as orders
import oandapyV20.endpoints.positions as positions
import oandapyV20.endpoints.accounts as accounts
from oandapyV20.exceptions import V20Error

from utils.logger import get_logger
from utils.config import settings

logger = get_logger(__name__)

# OANDA granularity → pandas freq 変換マップ
GRANULARITY_MAP = {
    "M1": "1min", "M5": "5min", "M15": "15min",
    "H1": "1h",   "H4": "4h",   "D": "1D",
}


class OandaClient:
    """OANDA v20 REST API クライアント"""

    MAX_CANDLES = 5000          # 1リクエストあたりの上限
    RETRY_LIMIT = 3
    RETRY_WAIT  = 2.0           # 秒

    def __init__(
        self,
        api_key: str | None = None,
        account_id: str | None = None,
        environment: str | None = None,
    ):
        self.api_key      = api_key      or settings.oanda_api_key
        self.account_id   = account_id   or settings.oanda_account_id
        self.environment  = environment  or settings.oanda_environment  # "practice" | "live"

        self._client = oandapyV20.API(
            access_token=self.api_key,
            environment=self.environment,
        )
        logger.info(f"OandaClient 初期化完了 (env={self.environment})")

    # ─────────────────────────────────────────────────────────────────────────
    # 公開メソッド
    # ─────────────────────────────────────────────────────────────────────────

    def fetch_candles(
        self,
        instrument: str = "USD_JPY",
        granularity: str = "H1",
        count: int = 500,
        from_dt: Optional[datetime] = None,
        to_dt:   Optional[datetime] = None,
    ) -> pd.DataFrame:
        """
        ローソク足データを取得して DataFrame で返す。

        Parameters
        ----------
        instrument  : 通貨ペア (例: "USD_JPY", "EUR_USD")
        granularity : 時間足 ("M1","M5","M15","H1","H4","D")
        count       : 取得本数（from_dt 指定時は無視）
        from_dt     : 取得開始日時（UTC）
        to_dt       : 取得終了日時（UTC、省略時=現在）

        Returns
        -------
        pd.DataFrame  columns: open, high, low, close, volume
        """
        params: dict = {"granularity": granularity, "price": "M"}  # Mid価格

        if from_dt:
            params["from"] = from_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            if to_dt:
                params["to"] = to_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            params["count"] = min(count, self.MAX_CANDLES)

        raw = self._request_with_retry(
            instruments.InstrumentsCandles(instrument, params=params)
        )
        df = self._parse_candles(raw)
        logger.info(
            f"ローソク足取得完了: {instrument} {granularity} "
            f"{len(df)}本 ({df.index[0]} ~ {df.index[-1]})"
        )
        return df

    def fetch_large_candles(
        self,
        instrument: str = "USD_JPY",
        granularity: str = "H1",
        total: int = 10_000,
    ) -> pd.DataFrame:
        """
        5000本超のデータを分割リクエストで取得する。
        """
        logger.info(f"大量取得開始: {instrument} {granularity} 合計{total}本")
        frames: list[pd.DataFrame] = []
        remaining = total

        # 最新から過去方向に向かって取得
        to_dt = datetime.now(timezone.utc)

        while remaining > 0:
            batch = min(remaining, self.MAX_CANDLES)
            params = {
                "granularity": granularity,
                "price": "M",
                "count": batch,
                "to": to_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            raw = self._request_with_retry(
                instruments.InstrumentsCandles(instrument, params=params)
            )
            df = self._parse_candles(raw)
            if df.empty:
                break
            frames.append(df)
            remaining -= len(df)
            to_dt = df.index[0].to_pydatetime()  # 次のバッチの終端
            time.sleep(0.3)  # レートリミット対策

        if not frames:
            return pd.DataFrame()

        result = pd.concat(frames).sort_index().drop_duplicates()
        logger.info(f"大量取得完了: {len(result)}本")
        return result

    def get_account_summary(self) -> dict:
        """口座残高・証拠金情報を取得する"""
        r = accounts.AccountSummary(self.account_id)
        return self._request_with_retry(r)

    # ─────────────────────────────────────────────────────────────────────────
    # プライベートメソッド
    # ─────────────────────────────────────────────────────────────────────────

    def _request_with_retry(self, endpoint) -> dict:
        """リトライ付きリクエスト実行"""
        for attempt in range(1, self.RETRY_LIMIT + 1):
            try:
                self._client.request(endpoint)
                return endpoint.response
            except V20Error as e:
                logger.warning(f"OANDA API エラー (試行 {attempt}/{self.RETRY_LIMIT}): {e}")
                if attempt == self.RETRY_LIMIT:
                    raise
                time.sleep(self.RETRY_WAIT * attempt)

    @staticmethod
    def _parse_candles(raw: dict) -> pd.DataFrame:
        """API レスポンスを DataFrame に変換する"""
        candles = raw.get("candles", [])
        if not candles:
            return pd.DataFrame()

        records = []
        for c in candles:
            if not c.get("complete", True):
                continue  # 未確定足をスキップ
            mid = c["mid"]
            records.append({
                "time":   c["time"],
                "open":   float(mid["o"]),
                "high":   float(mid["h"]),
                "low":    float(mid["l"]),
                "close":  float(mid["c"]),
                "volume": int(c["volume"]),
            })

        df = pd.DataFrame(records)
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time").sort_index()
        return df
