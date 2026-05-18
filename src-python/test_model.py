import pandas as pd
import numpy as np
from data.feature_engineer import FeatureEngineer
from data.preprocessor import Preprocessor
from models.xgb_model import XGBModel

np.random.seed(42)
n = 1000
dates = pd.date_range('2024-01-01', periods=n, freq='1h', tz='UTC')
price = 150.0 + np.cumsum(np.random.randn(n) * 0.1)
df = pd.DataFrame({
    'open':   price + np.random.randn(n) * 0.05,
    'high':   price + np.abs(np.random.randn(n)) * 0.1,
    'low':    price - np.abs(np.random.randn(n)) * 0.1,
    'close':  price,
    'volume': np.random.randint(100, 1000, n).astype(float),
}, index=dates)

pre      = Preprocessor()
fe       = FeatureEngineer()
features = fe.generate(pre.clean(df))
labels   = pre.create_labels(features, horizon=1, threshold=0.0003)
features = features.drop(columns=['open','high','low','close','volume'], errors='ignore')

n = len(features)
split = int(n * 0.8)
X_train, X_test = features.iloc[:split], features.iloc[split:]
y_train, y_test = labels.iloc[:split],   labels.iloc[split:]

model = XGBModel()
model.train(X_train, y_train, X_test, y_test)
metrics = model.evaluate(X_test, y_test)
print('Accuracy=' + str(round(metrics['accuracy'], 4)) + ' F1=' + str(round(metrics['f1'], 4)))
