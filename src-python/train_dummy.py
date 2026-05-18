import pandas as pd
import numpy as np
import sys, torch
sys.path.insert(0, '.')

from data.feature_engineer import FeatureEngineer
from data.preprocessor import Preprocessor
from models.xgb_model import XGBModel
from models.lstm_model import LSTMModel, _LSTMNet
from pathlib import Path
import joblib

print('Step 1: Generating data...')
np.random.seed(42)
n = 3000
dates = pd.date_range('2023-01-01', periods=n, freq='1h', tz='UTC')
price = 150.0 + np.cumsum(np.random.randn(n) * 0.1)
df = pd.DataFrame({
    'open':   price + np.random.randn(n) * 0.05,
    'high':   price + np.abs(np.random.randn(n)) * 0.1,
    'low':    price - np.abs(np.random.randn(n)) * 0.1,
    'close':  price,
    'volume': np.random.randint(100, 1000, n).astype(float),
}, index=dates)

print('Step 2: Feature engineering...')
pre      = Preprocessor()
fe       = FeatureEngineer()
cleaned  = pre.clean(df)
features = fe.generate(cleaned)
labels   = pre.create_labels(features, horizon=1, threshold=0.0003)
features = features.drop(columns=['open','high','low','close','volume'], errors='ignore')

n2 = len(features)
t1 = int(n2 * 0.7)
t2 = int(n2 * 0.85)
X_train = features.iloc[:t1]
X_val   = features.iloc[t1:t2]
X_test  = features.iloc[t2:]
y_train = labels.iloc[:t1]
y_val   = labels.iloc[t1:t2]
y_test  = labels.iloc[t2:]

print('Step 3: Training XGBoost...')
xgb = XGBModel()
xgb.train(X_train, y_train, X_val, y_val)

print('Step 4: Training LSTM...')
lstm = LSTMModel(seq_len=30, epochs=3, batch_size=32)
lstm.train(X_train, y_train, X_val, y_val)

print('Step 5: Saving models...')
save_path = Path('models/saved/USD_JPY/H1')
save_path.mkdir(parents=True, exist_ok=True)

xgb.save(save_path / 'xgb.joblib')
lstm.save(save_path / 'lstm.pt')
joblib.dump({
    'xgb_weight': 0.7,
    'lstm_weight': 0.3,
    'strategy': 'weighted_avg',
    'confidence_threshold': 0.45,
}, save_path / 'ensemble_config.joblib')

print('Done!')
metrics = xgb.evaluate(X_test, y_test, verbose=False)
print('XGB Accuracy=' + str(round(metrics['accuracy'], 4)))
