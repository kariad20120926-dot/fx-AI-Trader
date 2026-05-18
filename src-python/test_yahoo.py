import pandas as pd
import numpy as np
import sys
sys.path.insert(0, '.')

from data.yahoo_client import YahooClient
from data.feature_engineer import FeatureEngineer
from data.preprocessor import Preprocessor
from models.xgb_model import XGBModel
from models.lstm_model import LSTMModel
from pathlib import Path
import joblib

print('Step 1: Fetching Yahoo Finance data...')
client = YahooClient()
df = client.fetch_candles('USD_JPY', 'H1', count=2000)
print('Shape:', df.shape)
print('Columns:', df.columns.tolist())
print('Index sample:', df.index[:3])
print(df.head(3))

print('Step 2: Feature engineering...')
pre      = Preprocessor()
fe       = FeatureEngineer()
cleaned  = pre.clean(df)
print('Cleaned shape:', cleaned.shape)
features = fe.generate(cleaned)
print('Features shape:', features.shape)
