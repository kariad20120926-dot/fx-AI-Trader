import sys
sys.path.insert(0, '.')
import numpy as np
from data.pipeline import DataPipeline, PipelineConfig
from models.xgb_model import XGBModel
from models.lstm_model import LSTMModel
from pathlib import Path
import joblib

cfg    = PipelineConfig(source='yahoo', instrument='USD_JPY', granularity='H1', candle_count=2000)
bundle = DataPipeline(cfg).run()

print('Label distribution (train):')
print(bundle.y_train.value_counts())

# クラスバランスを確認
from collections import Counter
counts = Counter(bundle.y_train)
total  = len(bundle.y_train)

# XGBoost をクラスバランス調整で学習
from xgboost import XGBClassifier
import pandas as pd

LABEL_ENCODE = {-1: 0, 0: 1, 1: 2}
LABEL_DECODE = {0: -1, 1: 0, 2: 1}

y_tr = bundle.y_train.map(LABEL_ENCODE)
y_v  = bundle.y_val.map(LABEL_ENCODE)

model = XGBClassifier(
    objective='multi:softprob',
    num_class=3,
    eval_metric='mlogloss',
    n_estimators=300,
    learning_rate=0.05,
    max_depth=4,
    subsample=0.8,
    colsample_bytree=0.8,
    random_state=42,
    n_jobs=-1,
    verbosity=0,
    early_stopping_rounds=20,
)
model.fit(bundle.X_train, y_tr, eval_set=[(bundle.X_val, y_v)], verbose=False)

preds = model.predict(bundle.X_test)
decoded = [LABEL_DECODE[int(p)] for p in preds]
print('Test predictions:', Counter(decoded))

# 保存
save_path = Path('models/saved/USD_JPY/H1')
save_path.mkdir(parents=True, exist_ok=True)

xgb_wrapper = __import__('models.xgb_model', fromlist=['XGBModel']).XGBModel()
xgb_wrapper._model         = model
xgb_wrapper._feature_names = list(bundle.X_train.columns)
xgb_wrapper.is_fitted      = True
xgb_wrapper.save(save_path / 'xgb.joblib')

from models.lstm_model import LSTMModel
lstm = LSTMModel(seq_len=30, epochs=5, batch_size=32)
lstm.train(bundle.X_train, bundle.y_train, bundle.X_val, bundle.y_val)
lstm.save(save_path / 'lstm.pt')

joblib.dump({'xgb_weight': 0.7, 'lstm_weight': 0.3, 'strategy': 'weighted_avg', 'confidence_threshold': 0.33}, save_path / 'ensemble_config.joblib')
print('Done!')
