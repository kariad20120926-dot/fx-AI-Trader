import sys
sys.path.insert(0, '.')
from data.pipeline import DataPipeline, PipelineConfig
from models.ensemble import EnsembleModel
import numpy as np

cfg    = PipelineConfig(source='yahoo', instrument='USD_JPY', granularity='H1', candle_count=300)
bundle = DataPipeline(cfg).run()
model  = EnsembleModel()
model.load('models/saved/USD_JPY/H1')

info = model.signal(bundle.X_test)
print('Signal:', info['label'])
print('Confidence:', round(info['confidence']*100, 1))
print('BUY:', round(info['probabilities']['BUY']*100, 1))
print('SELL:', round(info['probabilities']['SELL']*100, 1))
print('HOLD:', round(info['probabilities']['HOLD']*100, 1))
proba = model.predict_proba(bundle.X_test)
print('Max:', round(float(np.max(proba))*100, 1))
