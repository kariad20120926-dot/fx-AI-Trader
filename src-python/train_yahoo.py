import pandas as pd
import numpy as np
import sys
sys.path.insert(0, '.')

from data.pipeline import DataPipeline, PipelineConfig
from models.xgb_model import XGBModel
from models.lstm_model import LSTMModel
from pathlib import Path
import joblib

print('Step 1: Fetching Yahoo Finance data...')
cfg    = PipelineConfig(source='yahoo', instrument='USD_JPY', granularity='H1', candle_count=2000)
bundle = DataPipeline(cfg).run()
print('train:', len(bundle.X_train), 'val:', len(bundle.X_val), 'test:', len(bundle.X_test))

print('Step 2: Training XGBoost...')
xgb = XGBModel()
xgb.train(bundle.X_train, bundle.y_train, bundle.X_val, bundle.y_val)

print('Step 3: Training LSTM...')
lstm = LSTMModel(seq_len=30, epochs=5, batch_size=32)
lstm.train(bundle.X_train, bundle.y_train, bundle.X_val, bundle.y_val)

print('Step 4: Saving...')
save_path = Path('models/saved/USD_JPY/H1')
save_path.mkdir(parents=True, exist_ok=True)
xgb.save(save_path / 'xgb.joblib')
lstm.save(save_path / 'lstm.pt')
joblib.dump({'xgb_weight': 0.7, 'lstm_weight': 0.3, 'strategy': 'weighted_avg', 'confidence_threshold': 0.45}, save_path / 'ensemble_config.joblib')

metrics = xgb.evaluate(bundle.X_test, bundle.y_test, verbose=False)
print('Done! XGB Accuracy=' + str(round(metrics['accuracy'], 4)) + ' F1=' + str(round(metrics['f1'], 4)))
