# -*- coding: utf-8 -*-
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import json

router = APIRouter()


@router.get("/evals")
def get_evals():
    from data.database import SessionLocal, ModelEval
    from sqlalchemy import desc
    db   = SessionLocal()
    rows = db.query(ModelEval).order_by(desc(ModelEval.timestamp)).limit(50).all()
    db.close()
    return [
        {
            "timestamp":   r.timestamp,
            "instrument":  r.instrument,
            "granularity": r.granularity,
            "f1_score":    r.f1_score,
            "accuracy":    r.accuracy,
            "win_rate":    r.win_rate,
            "sharpe_ratio":r.sharpe_ratio,
        }
        for r in rows
    ]


@router.post("/train")
async def train_model(instrument: str = "USD_JPY", granularity: str = "H1"):
    async def _stream():
        yield f"data: {json.dumps({'message': 'Starting...', 'progress': 5})}\n\n"
        try:
            from models.trainer import ModelTrainer
            from data.pipeline import PipelineConfig
            trainer = ModelTrainer(
                pipeline_config=PipelineConfig(
                    instrument=instrument,
                    granularity=granularity,
                    candle_count=5000,
                )
            )
            result = trainer.run()
            m = result["metrics"]["Ensemble"]
            yield f"data: {json.dumps({'message': 'Done', 'progress': 100, 'result': {'f1': round(m['f1'], 4), 'accuracy': round(m['accuracy'], 4)}})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'message': f'Error: {e}', 'progress': 100})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")
