import sys
sys.path.insert(0, '.')
import numpy as np
from data.pipeline import DataPipeline, PipelineConfig
from models.ensemble import EnsembleModel
from strategies.signal_generator import SignalGenerator

cfg    = PipelineConfig(source='yahoo', instrument='USD_JPY', granularity='H1', candle_count=500)
bundle = DataPipeline(cfg).run()

model = EnsembleModel()
model.load('models/saved/USD_JPY/H1')

# フィルターなしでシグナル生成
sg = SignalGenerator(model=model, confidence_min=0.0, adx_min=0.0)
sg.fit_thresholds(bundle.X_test)
signals = sg.generate(bundle.X_test)

print('Signal counts:', signals['direction'].value_counts().to_dict())
print('Raw model predictions:')
labels = model.predict(bundle.X_test)
import pandas as pd
print(pd.Series(labels).value_counts())
