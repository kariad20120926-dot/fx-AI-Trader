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

    def create_labels_triple_barrier(
        self,
        df:       pd.DataFrame,
        horizon:  int   = 24,
        sl_mult:  float = 2.0,
        tp_mult:  float = 3.0,
        atr_col:  str   = "atr_14",
    ) -> pd.Series:
        """
        トリプルバリア方式の教師ラベルを生成する（3クラス分類）。

        実際の取引ルール（SL=ATR×sl_mult, TP=ATR×tp_mult）と同一の条件で
        「ロングならTPがSLより先にヒットするか」を将来の高値・安値の経路から
        判定する。1本先の終値比較より取引結果との整合性が高い。

        Parameters
        ----------
        horizon  : バリア判定の最大バー数（時間切れは HOLD）
        sl_mult  : 損切りバリア = ATR × sl_mult
        tp_mult  : 利確バリア   = ATR × tp_mult
        atr_col  : ATR 列名（無ければ TR14 を内部計算）

        Returns
        -------
        pd.Series  値: 1=BUY勝ち, -1=SELL勝ち, 0=どちらも不成立
        """
        c = df["close"].values
        h = df["high"].values
        l = df["low"].values
        n = len(df)

        if atr_col in df.columns:
            atr = df[atr_col].values
        else:
            tr = pd.concat([
                df["high"] - df["low"],
                (df["high"] - df["close"].shift()).abs(),
                (df["low"]  - df["close"].shift()).abs(),
            ], axis=1).max(axis=1)
            atr = tr.rolling(14).mean().values

        # バリア価格（エントリー≒当バー終値と仮定）
        long_tp  = c + atr * tp_mult
        long_sl  = c - atr * sl_mult
        short_tp = c - atr * tp_mult
        short_sl = c + atr * sl_mult

        INF = np.iinfo(np.int32).max
        t_long_tp  = np.full(n, INF, dtype=np.int64)
        t_long_sl  = np.full(n, INF, dtype=np.int64)
        t_short_tp = np.full(n, INF, dtype=np.int64)
        t_short_sl = np.full(n, INF, dtype=np.int64)

        # 各バリアの初回ヒット時刻を将来 horizon 本まで走査
        for j in range(1, min(horizon, n - 1) + 1):
            hi_f = np.full(n, -np.inf)
            lo_f = np.full(n,  np.inf)
            hi_f[: n - j] = h[j:]
            lo_f[: n - j] = l[j:]

            hit = (hi_f >= long_tp)  & (t_long_tp  == INF)
            t_long_tp[hit] = j
            hit = (lo_f <= long_sl)  & (t_long_sl  == INF)
            t_long_sl[hit] = j
            hit = (lo_f <= short_tp) & (t_short_tp == INF)
            t_short_tp[hit] = j
            hit = (hi_f >= short_sl) & (t_short_sl == INF)
            t_short_sl[hit] = j

        # 同一バーでTP/SL両方に届いた場合はSL優先（保守的）→ 勝ちとみなさない
        long_win  = t_long_tp  < t_long_sl
        short_win = t_short_tp < t_short_sl

        labels = pd.Series(0, index=df.index, name="label")
        labels[long_win]  =  1
        labels[short_win & ~long_win] = -1
        # ATR が NaN の行はラベル不可
        labels[np.isnan(atr)] = 0

        logger.info(
            f"トリプルバリアラベル | BUY={(labels==1).sum()} "
            f"SELL={(labels==-1).sum()} HOLD={(labels==0).sum()} "
            f"(horizon={horizon}, SL={sl_mult}xATR, TP={tp_mult}xATR)"
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
        """
        不良ティック（スパイクして直後に反転するバー）のみを除去する。

        単に変化率が大きいバーを消すと、指標発表などの本物の急変動
        （まさにSLがヒットする局面）が履歴から消えてバックテストが
        楽観的になるため、「急変動 かつ 次バーでほぼ全戻し」の場合のみ
        データ異常とみなす。
        """
        ret = df["close"].pct_change()
        mean, std = ret.abs().mean(), ret.abs().std()
        spike  = ret.abs() > (mean + self.outlier_sigma * std)
        # 次バーで7割以上逆方向に戻していれば不良ティックとみなす
        revert = (ret.shift(-1) * ret) < (-0.7 * ret ** 2)
        bad = spike & revert.fillna(False)
        removed = bad.sum()
        if removed > 0:
            logger.warning(f"不良ティックを除去: {removed}行")
        return df[~bad]
