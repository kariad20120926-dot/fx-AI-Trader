# -*- coding: utf-8 -*-
"""
retrain_best.py — 勝率最大化のための最適学習スクリプト
使い方: python retrain_best.py
"""
import sys, os
sys.path.insert(0, '.')

import numpy as np
import pandas as pd
from pathlib import Path
from collections import Counter
import joblib

# ── 1. データ取得（Yahoo Finance 最大期間） ───────────────────────────────────
print("="*55)
print("Step 1: データ取得（Yahoo Finance 最大期間）")
print("="*55)

from data.yahoo_client import YahooClient
from data.feature_engineer import FeatureEngineer
from data.preprocessor import Preprocessor

client  = YahooClient()
raw     = client.fetch_candles("USD_JPY", "H1", count=9999)  # 取得できる最大
pre     = Preprocessor()
fe      = FeatureEngineer()
cleaned = pre.clean(raw)
features = fe.generate(cleaned)

# ラベル生成（threshold を下げてシグナルを増やす）
labels = pre.create_labels(features, horizon=1, threshold=0.0002)

# OHLCV 除去
ohlcv  = ["open","high","low","close","volume"]
X      = features.drop(columns=[c for c in ohlcv if c in features.columns])

n      = len(X)
t1     = int(n * 0.70)
t2     = int(n * 0.85)
X_train, X_val, X_test = X.iloc[:t1], X.iloc[t1:t2], X.iloc[t2:]
y_train, y_val, y_test = labels.iloc[:t1], labels.iloc[t1:t2], labels.iloc[t2:]

print(f"データ: train={len(X_train)} val={len(X_val)} test={len(X_test)}")
print(f"ラベル分布(train): {dict(y_train.value_counts())}")

# ── 2. XGBoost 最適学習 ────────────────────────────────────────────────────────
print("\n" + "="*55)
print("Step 2: XGBoost 学習（最適パラメーター）")
print("="*55)

from xgboost import XGBClassifier

ENCODE = {-1: 0, 0: 1, 1: 2}
DECODE = {0: -1, 1: 0, 2: 1}

y_tr = y_train.map(ENCODE)
y_v  = y_val.map(ENCODE)
y_te = y_test.map(ENCODE)

xgb = XGBClassifier(
    objective         = "multi:softprob",
    num_class         = 3,
    eval_metric       = "mlogloss",
    n_estimators      = 1000,          # 最大1000本（early stoppingで止まる）
    learning_rate     = 0.03,          # 小さめで精度向上
    max_depth         = 5,
    min_child_weight  = 5,
    subsample         = 0.8,
    colsample_bytree  = 0.7,
    gamma             = 0.2,
    reg_alpha         = 0.5,
    reg_lambda        = 1.5,
    early_stopping_rounds = 50,        # 50回改善しなければ停止
    random_state      = 42,
    n_jobs            = -1,
    verbosity         = 0,
)
xgb.fit(X_train, y_tr, eval_set=[(X_val, y_v)], verbose=False)

# テスト精度
preds  = xgb.predict(X_test)
decoded= [DECODE[int(p)] for p in preds]
from sklearn.metrics import accuracy_score, f1_score, classification_report
acc = accuracy_score(y_te, preds)
f1  = f1_score(y_te, preds, average="weighted", zero_division=0)
print(f"XGBoost - Accuracy: {acc:.4f}  F1: {f1:.4f}")
print(f"予測分布: {Counter(decoded)}")
print(classification_report(y_te, preds, target_names=["SELL","HOLD","BUY"], zero_division=0))

# ── 3. LSTM 学習 ───────────────────────────────────────────────────────────────
print("="*55)
print("Step 3: LSTM 学習（エポック数増加）")
print("="*55)

from models.lstm_model import LSTMModel
lstm = LSTMModel(
    seq_len    = 48,     # 48時間（2日分）のパターンを学習
    hidden_dim = 128,
    num_layers = 2,
    dropout    = 0.3,
    lr         = 5e-4,
    epochs     = 30,     # 30エポック（Early Stoppingで早期終了）
    batch_size = 64,
    patience   = 8,
)
lstm.train(X_train, y_train, X_val, y_val)

# ── 4. モデル保存 ──────────────────────────────────────────────────────────────
print("\n" + "="*55)
print("Step 4: モデル保存")
print("="*55)

save_path = Path("models/saved/USD_JPY/H1")
save_path.mkdir(parents=True, exist_ok=True)

# XGBoost
from models.xgb_model import XGBModel
xgb_wrapper = XGBModel()
xgb_wrapper._model         = xgb
xgb_wrapper._feature_names = list(X_train.columns)
xgb_wrapper.is_fitted      = True
xgb_wrapper.save(save_path / "xgb.joblib")

# LSTM
lstm.save(save_path / "lstm.pt")

# アンサンブル設定
joblib.dump({
    "xgb_weight":           0.65,
    "lstm_weight":          0.35,
    "strategy":             "weighted_avg",
    "confidence_threshold": 0.38,
}, save_path / "ensemble_config.joblib")

print(f"保存完了: {save_path}")
print("\n" + "="*55)
print("学習完了！")
print(f"  XGBoost Accuracy : {acc:.4f}")
print(f"  XGBoost F1       : {f1:.4f}")
print("="*55)
