# -*- coding: utf-8 -*-
import sys, os
BASE = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(BASE))

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from api.routes import signals, trades, backtest, settings
from api.routes.model import router as model_router
from api.routes.chart import router as chart_router

scheduler = AsyncIOScheduler(timezone="UTC")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from api.scheduler import register_jobs
    register_jobs(scheduler)
    scheduler.start()
    print("[API] started port=8742", flush=True)
    yield
    scheduler.shutdown(wait=False)
    print("[API] stopped", flush=True)


app = FastAPI(title="FX AI Trader API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["tauri://localhost", "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(signals.router,  prefix="/api/signals",  tags=["signals"])
app.include_router(trades.router,   prefix="/api/trades",   tags=["trades"])
app.include_router(backtest.router, prefix="/api/backtest", tags=["backtest"])
app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
app.include_router(model_router,    prefix="/api/model",    tags=["model"])
app.include_router(chart_router,    prefix="/api/chart",    tags=["chart"])


@app.get("/health")
async def health():
    return {"status": "ok", "port": 8742}


if __name__ == "__main__":
    uvicorn.run("api.server:app", host="127.0.0.1", port=8742, reload=False)
