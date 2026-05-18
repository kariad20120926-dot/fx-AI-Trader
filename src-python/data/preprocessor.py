"""
src/data/preprocessor.py — データ前処理モジュール
欠損値処理・外れ値除去・正規化を担当する
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler
from utils.logger import get_logger

logger = get_logger(__name__)


class Preprocessor:
    """OHLCV DataFrame の前処理クラス"""

    def __init__(self, fill_method: str = "ffill", outlier_sigma: float = 4.0):
        """
        Parameters
        ----------
        fill_method    : 欠損値補完方式 ("ffill" | "interpolate" | "drop")
        outlier_sigma  : 外れ値判定の標準偏差閾値
        """
        self.fill_method   = fill_method
        self.outlier_sigma = outlier_sigma
        self._scaler       = RobustScaler()

    # ─────────────────────────────────────────────────────────────────────────
    # 公開メソッド
    # ─────────────────────────────────────────────────────────────────────────

    def clean(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        OHLCV データのクリーニングを行う。

        処理順序:
          1. 重複インデックスの削除
          2. 欠損値の補完
          3. OHLC の整合性チェック（high >= low, high >= open/close など）
          4. 外れ値の除去
        """
        logger.info(f"前処理開始: {len(df)}行")
        df = df.copy()

        # 1. 重複インデックスを削除
        before = len(df)
        df = df[~df.index.duplicated(keep="last")]
        if (removed := before - len(df)) > 0:
            logger.debug(f"重複行を削除: {removed}行")

        # 2. 欠損値の補完
        df = self._fill_missing(df)

        # 3. OHLC 整合性チェック
        df = self._fix_ohlc_integrity(df)

        # 4. 外れ値除去
        df = self._remove_outliers(df)

        logger.info(f"前処理完了: {len(df)}行")
        return df

    def scale(self, df: pd.DataFrame, fit: bool = True) -> pd.DataFrame:
        """
        数値列を RobustScaler で正規化する。

        Parameters
        ----------
        df  : 特徴量 DataFrame
        fit : True=フィット＋変換、False=変換のみ（推論時）
        """
        cols = df.select_dtypes(include=[np.number]).columns
        result = df.copy()
        if fit:
            result[cols] = self._scaler.fit_transform(df[cols])
        else:
            result[cols] = self._scaler.transform(df[cols])
        return result

    def inverse_scale(self, df: pd.DataFrame) -> pd.DataFrame:
        """scale() の逆変換"""
        cols = df.select_dtypes(include=[np.number]).columns
        result = df.copy()
        result[cols] = self._scaler.inverse_transform(df[cols])
        return result

    def create_labels(
        self,
        df: pd.DataFrame,
        horizon: int = 1,
        threshold: float = 0.0003,
    ) -> pd.Series:
        """
        教師ラベルを生成する（3クラス分類）。

        Parameters
        ----------
        horizon   : 何本先の終値で判定するか
        threshold : 変化率の閾値（0.03% = 3pips 相当）

        Returns
        -------
        pd.Series  値: 1=BUY, -1=SELL, 0=HOLD
        """
        future_ret = df["close"].shift(-horizon) / df["close"] - 1
        labels = pd.Series(0, index=df.index, name="label")
        labels[future_ret >  threshold] =  1   # BUY
        labels[future_ret < -threshold] = -1   # SELL
        logger.debug(
            f"ラベル分布 | BUY={( labels==1).sum()} "
            f"SELL={(labels==-1).sum()} HOLD={(labels==0).sum()}"
        )
        return labels

    # ─────────────────────────────────────────────────────────────────────────
    # プライベートメソッド
    # ─────────────────────────────────────────────────────────────────────────

    def _fill_missing(self, df: pd.DataFrame) -> pd.DataFrame:
        missing = df.isnull().sum().sum()
        if missing == 0:
            return df
        logger.debug(f"欠損値補完: {missing}セル ({self.fill_method})")
        if self.fill_method == "ffill":
            return df.ffill().bfill()
        elif self.fill_method == "interpolate":
            return df.interpolate(method="time").bfill()
        elif self.fill_method == "drop":
            return df.dropna()
        return df

    def _fix_ohlc_integrity(self, df: pd.DataFrame) -> pd.DataFrame:
        """OHLC 整合性の修正（high が low より低いなどの異常データを補正）"""
        if not {"open", "high", "low", "close"}.issubset(df.columns):
            return df
        # high は open/close の最大値以上にする
        df["high"] = df[["high", "open", "close"]].max(axis=1)
        # low は open/close の最小値以下にする
        df["low"]  = df[["low",  "open", "close"]].min(axis=1)
        return df

    def _remove_outliers(self, df: pd.DataFrame) -> pd.DataFrame:
        """終値の変化率が sigma 倍を超える行を外れ値として除去"""
        ret = df["close"].pct_change().abs()
        mean, std = ret.mean(), ret.std()
        mask = ret < (mean + self.outlier_sigma * std)
        removed = (~mask).sum()
        if removed > 0:
            logger.warning(f"外れ値を除去: {removed}行")
        return df[mask]
