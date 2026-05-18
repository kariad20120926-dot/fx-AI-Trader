"""
src/models/trainer.py — モデル学習・評価・保存の統合スクリプト
DataPipeline → EnsembleModel の一連のフローを管理する
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from data.pipeline import DataPipeline, PipelineConfig, DataBundle
from models.ensemble import EnsembleModel
from utils.logger import get_logger

logger = get_logger(__name__)

MODEL_DIR = Path("models/saved")


class ModelTrainer:
    """
    データ取得からモデル保存まで一括管理するトレーナー。

    使い方:
        trainer = ModelTrainer()
        result  = trainer.run()
        # → result["metrics"] で評価結果を確認
    """

    def __init__(
        self,
        pipeline_config: Optional[PipelineConfig] = None,
        xgb_weight:      float = 0.55,
        lstm_weight:     float = 0.45,
        optimize_weights: bool = True,
        model_dir:       Path  = MODEL_DIR,
    ):
        self.pipeline_config  = pipeline_config or PipelineConfig()
        self.xgb_weight       = xgb_weight
        self.lstm_weight      = lstm_weight
        self.optimize_weights = optimize_weights
        self.model_dir        = model_dir

    def run(self) -> dict:
        """フルパイプラインを実行する"""
        logger.info("=" * 60)
        logger.info("モデル学習パイプライン開始")
        logger.info("=" * 60)

        # Step 1: データ準備
        bundle = self._prepare_data()

        # Step 2: モデル構築・学習
        model = self._train_model(bundle)

        # Step 3: 重み最適化
        if self.optimize_weights:
            model.optimize_weights(bundle.X_val, bundle.y_val)

        # Step 4: 評価
        metrics = model.evaluate_each(bundle.X_test, bundle.y_test)

        # Step 5: 保存
        self._save(model)

        logger.info("=" * 60)
        logger.info("モデル学習パイプライン完了")
        logger.info("=" * 60)
        return {"model": model, "metrics": metrics, "bundle": bundle}

    def _prepare_data(self) -> DataBundle:
        logger.info("データ準備中...")
        pipeline = DataPipeline(self.pipeline_config)
        bundle   = pipeline.run()
        logger.info(
            f"データ準備完了 | "
            f"train={len(bundle.X_train)} val={len(bundle.X_val)} test={len(bundle.X_test)}"
        )
        return bundle

    def _train_model(self, bundle: DataBundle) -> EnsembleModel:
        model = EnsembleModel(
            xgb_weight=self.xgb_weight,
            lstm_weight=self.lstm_weight,
        )
        model.train(
            bundle.X_train, bundle.y_train,
            bundle.X_val,   bundle.y_val,
        )
        return model

    def _save(self, model: EnsembleModel) -> None:
        save_path = self.model_dir / self.pipeline_config.instrument / self.pipeline_config.granularity
        model.save(save_path)
        logger.info(f"モデル保存完了: {save_path}")


# ─────────────────────────────────────────────────────────────────────────────
# CLI エントリーポイント
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="FX AI モデルの学習")
    parser.add_argument("--instrument",  default="USD_JPY", help="通貨ペア")
    parser.add_argument("--granularity", default="H1",      help="時間足")
    parser.add_argument("--count",       type=int, default=5000, help="取得ローソク足数")
    parser.add_argument("--source",      default="oanda",   help="データソース (oanda/mt5)")
    args = parser.parse_args()

    cfg = PipelineConfig(
        source=args.source,
        instrument=args.instrument,
        granularity=args.granularity,
        candle_count=args.count,
    )
    trainer = ModelTrainer(pipeline_config=cfg)
    result  = trainer.run()

    # 最終結果の表示
    ens_metrics = result["metrics"]["Ensemble"]
    print(f"\n最終評価 (テストデータ)")
    print(f"  Accuracy : {ens_metrics['accuracy']:.4f}")
    print(f"  F1 Score : {ens_metrics['f1']:.4f}")
