# -*- coding: utf-8 -*-
"""
data/pipeline.py — データパイプライン
Twelve Data / Yahoo Finance / OANDA からデータ取得して特徴量生成・分割を行う
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd
from utils.logger import get_logger

logger = get_logger(__name__)


def get_twelvedata_key() -> str:
    try:
        from data.database import SessionLocal, AppSetting
        db  = SessionLocal()
        row = db.query(AppSetting).filter(AppSetting.key == "twelvedata_api_key").first()
        db.close()
        return row.value if row and row.value else ""
    except Exception:
        return ""


@dataclass
class PipelineConfig:
    source:       str   = "auto"        # "auto" | "twelvedata" | "yahoo" | "oanda" | "dummy"
    instrument:   str   = "USD_JPY"
    granularity:  str   = "H1"
    candle_count: int   = 2000
    horizon:      int   = 1
    threshold:    float = 0.0002
    test_ratio:   float = 0.2
    val_ratio:    float = 0.1
    drop_ohlcv:   bool  = True


@dataclass
class DataBundle:
    X_train: pd.DataFrame
    X_val:   pd.DataFrame
    X_test:  pd.DataFrame
    y_train: pd.Series
    y_val:   pd.Series
    y_test:  pd.Series
    raw:     pd.DataFrame
    feature_names: list = field(default_factory=list)


class DataPipeline:
    def __init__(self, config: Optional[PipelineConfig] = None):
        self.cfg = config or PipelineConfig()
        from data.preprocessor import Preprocessor
        from data.feature_engineer import FeatureEngineer
        self.preprocessor = Preprocessor()
        self.feature_eng  = FeatureEngineer()

    def run(self) -> DataBundle:
        logger.info(f"パイプライン開始: {self.cfg.instrument} {self.cfg.granularity} ({self.cfg.source})")
        raw      = self._fetch()
        cleaned  = self.preprocessor.clean(raw)
        features = self.feature_eng.generate(cleaned)
        labels   = self.preprocessor.create_labels(
            features, horizon=self.cfg.horizon, threshold=self.cfg.threshold
        )
        raw_full = features[["open","high","low","close","volume"]].copy() \
            if all(c in features.columns for c in ["open","high","low","close","volume"]) \
            else cleaned.loc[features.index]

        if self.cfg.drop_ohlcv:
            ohlcv = ["open","high","low","close","volume"]
            features = features.drop(columns=[c for c in ohlcv if c in features.columns])

        bundle = self._split(features, labels, raw_full)
        logger.info(f"パイプライン完了: train={len(bundle.X_train)} val={len(bundle.X_val)} test={len(bundle.X_test)}")
        return bundle

    def fetch_latest(self, count: int = 600) -> pd.DataFrame:
        raw      = self._fetch(count=count)
        cleaned  = self.preprocessor.clean(raw)
        features = self.feature_eng.generate(cleaned)
        if self.cfg.drop_ohlcv:
            ohlcv = ["open","high","low","close","volume"]
            features = features.drop(columns=[c for c in ohlcv if c in features.columns])
        return features.dropna()

    def _fetch(self, count: Optional[int] = None) -> pd.DataFrame:
        n      = count or self.cfg.candle_count
        source = self.cfg.source

        # auto: Twelve Data → Yahoo Finance の順で試す
        if source == "auto":
            td_key = get_twelvedata_key()
            if td_key:
                source = "twelvedata"
            else:
                source = "yahoo"

        if source == "twelvedata":
            td_key = get_twelvedata_key()
            if not td_key:
                logger.warning("Twelve Data APIキー未設定、Yahoo Financeにフォールバック")
                source = "yahoo"
            else:
                try:
                    from data.twelvedata_client import TwelveDataClient
                    return TwelveDataClient(td_key).fetch_candles(
                        instrument=self.cfg.instrument,
                        granularity=self.cfg.granularity,
                        count=n,
                    )
                except Exception as e:
                    logger.warning(f"Twelve Data失敗({e})、Yahoo Financeにフォールバック")
                    source = "yahoo"

        if source == "yahoo":
            from data.yahoo_client import YahooClient
            return YahooClient().fetch_candles(
                instrument=self.cfg.instrument,
                granularity=self.cfg.granularity,
                count=n,
            )

        if source == "oanda":
            from data.oanda_client import OandaClient
            return OandaClient().fetch_candles(
                instrument=self.cfg.instrument,
                granularity=self.cfg.granularity,
                count=n,
            )

        if source == "dummy":
            return self._make_dummy(n)

        raise ValueError(f"不明なデータソース: {source}")

    def _make_dummy(self, n: int) -> pd.DataFrame:
        import numpy as np
        logger.warning("ダミーデータを使用します（テスト用）")
        np.random.seed(42)
        dates = pd.date_range("2023-01-01", periods=n, freq="1h", tz="UTC")
        price = 150.0 + np.cumsum(np.random.randn(n) * 0.1)
        return pd.DataFrame({
            "open":   price + np.random.randn(n) * 0.05,
            "high":   price + np.abs(np.random.randn(n)) * 0.1,
            "low":    price - np.abs(np.random.randn(n)) * 0.1,
            "close":  price,
            "volume": np.zeros(n),
        }, index=dates)

    def _split(self, X, y, raw) -> DataBundle:
        n       = len(X)
        test_n  = int(n * self.cfg.test_ratio)
        val_n   = int(n * self.cfg.val_ratio)
        train_n = n - val_n - test_n
        return DataBundle(
            X_train=X.iloc[:train_n],
            X_val=X.iloc[train_n:train_n+val_n],
            X_test=X.iloc[train_n+val_n:],
            y_train=y.iloc[:train_n],
            y_val=y.iloc[train_n:train_n+val_n],
            y_test=y.iloc[train_n+val_n:],
            raw=raw,
            feature_names=list(X.columns),
        )
