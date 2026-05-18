import sys
sys.path.insert(0, '.')
import numpy as np
from data.pipeline import DataPipeline, PipelineConfig
from models.ensemble import EnsembleModel

cfg    = PipelineConfig(source='yahoo', instrument='USD_JPY', granularity='H1', candle_count=500)
bundle = DataPipeline(cfg).run()

model = EnsembleModel()
model.load('models/saved/USD_JPY/H1')

proba = model.predict_proba(bundle.X_test)
print('Max confidence per sample (first 20):')
print(np.max(proba, axis=1)[:20].round(3))
print('Mean max confidence:', np.max(proba, axis=1).mean().round(3))
print('Samples above 0.40:', (np.max(proba, axis=1) > 0.40).sum())
print('Samples above 0.35:', (np.max(proba, axis=1) > 0.35).sum())
print('Samples above 0.34:', (np.max(proba, axis=1) > 0.34).sum())
