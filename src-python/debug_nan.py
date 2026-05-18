import pandas as pd
import numpy as np
import sys
sys.path.insert(0, '.')

from data.yahoo_client import YahooClient
from data.preprocessor import Preprocessor
from data.feature_engineer import FeatureEngineer

client  = YahooClient()
df      = client.fetch_candles('USD_JPY', 'H1', count=300)
pre     = Preprocessor()
fe      = FeatureEngineer(drop_na=False)  # drop_na を無効化して確認
cleaned = pre.clean(df)
features = fe.generate(cleaned)

print('Features shape (no drop):', features.shape)

# どの列がNaNか確認
nan_counts = features.isna().sum()
print('Columns with ALL NaN:')
print(nan_counts[nan_counts == len(features)].index.tolist())
print('Columns with SOME NaN (top 10):')
print(nan_counts[nan_counts > 0].sort_values(ascending=False).head(10))
