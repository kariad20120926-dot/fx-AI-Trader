import pandas as pd
import numpy as np
import sys
sys.path.insert(0, '.')

from data.yahoo_client import YahooClient
from data.preprocessor import Preprocessor

client  = YahooClient()
df      = client.fetch_candles('USD_JPY', 'H1', count=300)
pre     = Preprocessor()
cleaned = pre.clean(df)

print('Index type:', type(cleaned.index))
print('Index dtype:', cleaned.index.dtype)
print('Index name:', cleaned.index.name)

# 一目均衡表の計算を手動でテスト
h = cleaned['high']
l = cleaned['low']
tenkan = (h.rolling(9).max() + l.rolling(9).min()) / 2
print('tenkan NaN count:', tenkan.isna().sum(), 'out of', len(tenkan))

# 手動で特徴量を1列だけ計算
cleaned['sma_5'] = cleaned['close'].rolling(5).mean()
print('sma_5 NaN count:', cleaned['sma_5'].isna().sum())
print('sma_5 sample:', cleaned['sma_5'].dropna().head(3))

# ichimoku_chikou
chikou = cleaned['close'].shift(-26)
print('chikou NaN count:', chikou.isna().sum(), '(last 26 are NaN by design)')
print('drop_na after all features would remove:', chikou.isna().sum(), 'rows')
