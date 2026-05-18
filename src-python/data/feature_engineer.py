"""
src/data/feature_engineer.py — テクニカル指標による特徴量生成
pandas-ta をベースに、FX 予測に有効な50以上の特徴量を生成する
"""
from __future__ import annotations

import numpy as np
import pandas as pd

try:
    import pandas_ta as ta
    TA_AVAILABLE = True
except ImportError:
    TA_AVAILABLE = False

from utils.logger import get_logger

logger = get_logger(__name__)


class FeatureEngineer:
    """
    OHLCV DataFrame からテクニカル指標・統計特徴量を生成するクラス。

    生成カテゴリ:
      - トレンド系   : MA, EMA, MACD, ADX, Ichimoku
      - オシレーター : RSI, Stochastic, Williams %R, CCI
      - ボラティリティ: ATR, Bollinger Bands, Keltner Channel
      - 出来高       : OBV, VWAP
      - 価格パターン : ローソク足の実体・ヒゲ比率
      - 時間特徴量   : 時間帯・曜日（周期エンコーディング）
    """

    def __init__(self, drop_na: bool = True):
        self.drop_na = drop_na

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        全カテゴリの特徴量を生成して返す。

        Parameters
        ----------
        df : OHLCV DataFrame（index=DatetimeIndex UTC）

        Returns
        -------
        pd.DataFrame  特徴量列が追加された DataFrame
        """
        logger.info(f"特徴量生成開始: 入力 {len(df)}行 × {len(df.columns)}列")
        out = df.copy()

        out = self._add_trend_features(out)
        out = self._add_oscillator_features(out)
        out = self._add_volatility_features(out)
        out = self._add_volume_features(out)
        out = self._add_candle_pattern_features(out)
        out = self._add_time_features(out)
        out = self._add_lag_features(out)

        if self.drop_na:
            before = len(out)
            out = out.dropna()
            logger.debug(f"NaN を含む行を削除: {before - len(out)}行")

        logger.info(f"特徴量生成完了: {len(out)}行 × {len(out.columns)}列")
        return out

    # ─────────────────────────────────────────────────────────────────────────
    # トレンド系
    # ─────────────────────────────────────────────────────────────────────────

    def _add_trend_features(self, df: pd.DataFrame) -> pd.DataFrame:
        c = df["close"]

        # 移動平均（SMA）
        for p in [5, 10, 20, 50, 200]:
            df[f"sma_{p}"] = c.rolling(p).mean()

        # 指数移動平均（EMA）
        for p in [9, 21, 55]:
            df[f"ema_{p}"] = c.ewm(span=p, adjust=False).mean()

        # EMA 乖離率
        df["ema_9_dev"]  = (c - df["ema_9"])  / df["ema_9"]
        df["ema_21_dev"] = (c - df["ema_21"]) / df["ema_21"]

        # MACD
        ema12 = c.ewm(span=12, adjust=False).mean()
        ema26 = c.ewm(span=26, adjust=False).mean()
        df["macd"]        = ema12 - ema26
        df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
        df["macd_hist"]   = df["macd"] - df["macd_signal"]

        # ADX（トレンド強度）
        df = self._calc_adx(df, period=14)

        # 一目均衡表
        df = self._calc_ichimoku(df)

        return df

    # ─────────────────────────────────────────────────────────────────────────
    # オシレーター系
    # ─────────────────────────────────────────────────────────────────────────

    def _add_oscillator_features(self, df: pd.DataFrame) -> pd.DataFrame:
        c, h, l = df["close"], df["high"], df["low"]

        # RSI
        for p in [9, 14, 21]:
            df[f"rsi_{p}"] = self._calc_rsi(c, p)

        # Stochastic %K, %D
        low14  = l.rolling(14).min()
        high14 = h.rolling(14).max()
        df["stoch_k"] = 100 * (c - low14) / (high14 - low14 + 1e-10)
        df["stoch_d"] = df["stoch_k"].rolling(3).mean()

        # Williams %R
        df["williams_r"] = -100 * (high14 - c) / (high14 - low14 + 1e-10)

        # CCI（商品チャンネル指数）
        typical = (h + l + c) / 3
        ma20  = typical.rolling(20).mean()
        md20  = typical.rolling(20).apply(lambda x: np.mean(np.abs(x - x.mean())))
        df["cci"] = (typical - ma20) / (0.015 * md20 + 1e-10)

        # モメンタム
        for p in [5, 10, 20]:
            df[f"mom_{p}"] = c.diff(p)

        # ROC（変化率）
        for p in [5, 10]:
            df[f"roc_{p}"] = c.pct_change(p) * 100

        return df

    # ─────────────────────────────────────────────────────────────────────────
    # ボラティリティ系
    # ─────────────────────────────────────────────────────────────────────────

    def _add_volatility_features(self, df: pd.DataFrame) -> pd.DataFrame:
        h, l, c = df["high"], df["low"], df["close"]

        # ATR（True Range）
        tr = pd.concat([
            h - l,
            (h - c.shift()).abs(),
            (l - c.shift()).abs(),
        ], axis=1).max(axis=1)
        df["atr_14"] = tr.rolling(14).mean()
        df["atr_7"]  = tr.rolling(7).mean()

        # Bollinger Bands（20期間, 2σ）
        sma20 = c.rolling(20).mean()
        std20 = c.rolling(20).std()
        df["bb_upper"] = sma20 + 2 * std20
        df["bb_lower"] = sma20 - 2 * std20
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / sma20
        df["bb_pos"]   = (c - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"] + 1e-10)

        # 実現ボラティリティ（対数リターンの標準偏差）
        log_ret = np.log(c / c.shift())
        df["rv_10"] = log_ret.rolling(10).std() * np.sqrt(10)
        df["rv_20"] = log_ret.rolling(20).std() * np.sqrt(20)

        return df

    # ─────────────────────────────────────────────────────────────────────────
    # 出来高系
    # ─────────────────────────────────────────────────────────────────────────

    def _add_volume_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if "volume" not in df.columns:
            return df
        v, c = df["volume"], df["close"]

        # volume が全ゼロ（FX等）の場合はスキップ
        if v.sum() == 0:
            df["obv"]         = 0.0
            df["vol_ratio_10"]= 1.0
            df["vol_ratio_20"]= 1.0
            df["vwap"]        = c
            df["vwap_dev"]    = 0.0
            return df

        # OBV（On Balance Volume）
        direction = np.sign(c.diff())
        df["obv"] = (v * direction).cumsum()

        # 出来高移動平均比
        vol_ma10 = v.rolling(10).mean()
        vol_ma20 = v.rolling(20).mean()
        df["vol_ratio_10"] = v / (vol_ma10 + 1e-10)
        df["vol_ratio_20"] = v / (vol_ma20 + 1e-10)

        # VWAP（日次リセット付き）
        typical = (df["high"] + df["low"] + c) / 3
        vol_sum20 = v.rolling(20).sum()
        df["vwap"] = (typical * v).rolling(20).sum() / (vol_sum20 + 1e-10)
        df["vwap_dev"] = (c - df["vwap"]) / (df["vwap"] + 1e-10)

        return df

    # ─────────────────────────────────────────────────────────────────────────
    # ローソク足パターン
    # ─────────────────────────────────────────────────────────────────────────

    def _add_candle_pattern_features(self, df: pd.DataFrame) -> pd.DataFrame:
        o, h, l, c = df["open"], df["high"], df["low"], df["close"]
        body   = (c - o).abs()
        rng    = h - l + 1e-10

        df["body_ratio"]       = body / rng              # 実体の割合
        df["upper_shadow"]     = (h - pd.concat([c, o], axis=1).max(axis=1)) / rng
        df["lower_shadow"]     = (pd.concat([c, o], axis=1).min(axis=1) - l) / rng
        df["bullish"]          = (c > o).astype(int)     # 陽線フラグ
        df["doji"]             = (body / rng < 0.1).astype(int)  # 十字線

        return df

    # ─────────────────────────────────────────────────────────────────────────
    # 時間特徴量（周期エンコーディング）
    # ─────────────────────────────────────────────────────────────────────────

    def _add_time_features(self, df: pd.DataFrame) -> pd.DataFrame:
        idx = df.index

        # 時間（0-23）→ sin/cos で周期性を表現
        hour = idx.hour
        df["hour_sin"] = np.sin(2 * np.pi * hour / 24)
        df["hour_cos"] = np.cos(2 * np.pi * hour / 24)

        # 曜日（0=月 ~ 4=金）
        dow = idx.dayofweek
        df["dow_sin"] = np.sin(2 * np.pi * dow / 5)
        df["dow_cos"] = np.cos(2 * np.pi * dow / 5)

        # 東京・ロンドン・NY セッションフラグ
        df["session_tokyo"]  = ((hour >= 0)  & (hour < 9)).astype(int)
        df["session_london"] = ((hour >= 8)  & (hour < 17)).astype(int)
        df["session_ny"]     = ((hour >= 13) & (hour < 22)).astype(int)
        df["session_overlap"] = (
            ((hour >= 8)  & (hour < 9))   |   # 東京×ロンドン
            ((hour >= 13) & (hour < 17))       # ロンドン×NY
        ).astype(int)

        return df

    # ─────────────────────────────────────────────────────────────────────────
    # ラグ特徴量
    # ─────────────────────────────────────────────────────────────────────────

    def _add_lag_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """終値リターンの過去値（ラグ特徴量）"""
        ret = df["close"].pct_change()
        for lag in [1, 2, 3, 5, 10]:
            df[f"ret_lag_{lag}"] = ret.shift(lag)
        return df

    # ─────────────────────────────────────────────────────────────────────────
    # ヘルパー計算
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain  = delta.clip(lower=0).rolling(period).mean()
        loss  = (-delta.clip(upper=0)).rolling(period).mean()
        rs    = gain / (loss + 1e-10)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _calc_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        h, l, c = df["high"], df["low"], df["close"]
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        dm_plus  = ((h - h.shift()) > (l.shift() - l)).astype(float) * (h - h.shift()).clip(lower=0)
        dm_minus = ((l.shift() - l) > (h - h.shift())).astype(float) * (l.shift() - l).clip(lower=0)
        atr  = tr.rolling(period).mean()
        di_p = 100 * dm_plus.rolling(period).mean()  / (atr + 1e-10)
        di_m = 100 * dm_minus.rolling(period).mean() / (atr + 1e-10)
        dx   = 100 * (di_p - di_m).abs() / (di_p + di_m + 1e-10)
        df["adx"]    = dx.rolling(period).mean()
        df["di_plus"]  = di_p
        df["di_minus"] = di_m
        return df

    @staticmethod
    def _calc_ichimoku(df: pd.DataFrame) -> pd.DataFrame:
        h, l = df["high"], df["low"]
        tenkan  = (h.rolling(9).max()  + l.rolling(9).min())  / 2
        kijun   = (h.rolling(26).max() + l.rolling(26).min()) / 2
        df["ichimoku_tenkan"]   = tenkan
        df["ichimoku_kijun"]    = kijun
        df["ichimoku_span_a"]   = ((tenkan + kijun) / 2).shift(26)
        df["ichimoku_span_b"]   = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)
        df["ichimoku_chikou"]   = df["close"].shift(-26)
        df["cloud_thickness"]   = (df["ichimoku_span_a"] - df["ichimoku_span_b"]).abs()
        return df
