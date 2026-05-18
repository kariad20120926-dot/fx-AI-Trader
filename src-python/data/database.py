# -*- coding: utf-8 -*-
import os
from pathlib import Path
from sqlalchemy import create_engine, Column, String, Float, Integer, Boolean, DateTime, Text, Index
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from sqlalchemy.pool import StaticPool


def get_db_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", "~")).expanduser()
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser()
    db_dir = base / "fx-ai-trader"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "trader.db"


DB_PATH = get_db_path()
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class Signal(Base):
    __tablename__ = "signals"
    id            = Column(String, primary_key=True)
    timestamp     = Column(DateTime, nullable=False, index=True)
    instrument    = Column(String, nullable=False, index=True)
    granularity   = Column(String, nullable=False)
    signal        = Column(String, nullable=False)
    confidence    = Column(Float,  nullable=False)
    prob_buy      = Column(Float)
    prob_sell     = Column(Float)
    prob_hold     = Column(Float)
    entry_price   = Column(Float)
    stop_loss     = Column(Float)
    take_profit   = Column(Float)
    lot_size      = Column(Float)
    risk_reward   = Column(Float)
    filtered      = Column(Boolean, default=False)
    filter_reason = Column(String)
    model_version = Column(String)


class Trade(Base):
    __tablename__ = "trades"
    id          = Column(String, primary_key=True)
    signal_id   = Column(String, index=True)
    instrument  = Column(String, nullable=False, index=True)
    granularity = Column(String, nullable=False)
    direction   = Column(String, nullable=False)
    entry_time  = Column(DateTime, nullable=False)
    exit_time   = Column(DateTime)
    entry_price = Column(Float, nullable=False)
    exit_price  = Column(Float)
    stop_loss   = Column(Float, nullable=False)
    take_profit = Column(Float, nullable=False)
    lot_size    = Column(Float, nullable=False)
    pnl         = Column(Float)
    pnl_pips    = Column(Float)
    exit_reason = Column(String)
    confidence  = Column(Float)
    status      = Column(String, nullable=False, default="open")


class ModelEval(Base):
    __tablename__ = "model_evals"
    id            = Column(String, primary_key=True)
    timestamp     = Column(DateTime, nullable=False, index=True)
    instrument    = Column(String, nullable=False)
    granularity   = Column(String, nullable=False)
    model_version = Column(String)
    accuracy      = Column(Float)
    f1_score      = Column(Float)
    precision     = Column(Float)
    recall        = Column(Float)
    win_rate      = Column(Float)
    profit_factor = Column(Float)
    sharpe_ratio  = Column(Float)
    max_drawdown  = Column(Float)
    train_rows    = Column(Integer)


class AppSetting(Base):
    __tablename__ = "settings"
    key   = Column(String, primary_key=True)
    value = Column(Text, nullable=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
