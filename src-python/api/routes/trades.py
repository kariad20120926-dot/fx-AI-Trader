# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional
from data.database import get_db, Trade

router = APIRouter()


@router.get("")
def list_trades(
    instrument: Optional[str] = Query(None),
    status:     Optional[str] = Query(None),
    limit:      int           = Query(100, le=1000),
    db: Session               = Depends(get_db),
):
    q = db.query(Trade)
    if instrument:
        q = q.filter(Trade.instrument == instrument)
    if status:
        q = q.filter(Trade.status == status)
    return q.order_by(desc(Trade.entry_time)).limit(limit).all()


@router.get("/stats")
def trade_stats(db: Session = Depends(get_db)):
    closed = db.query(Trade).filter(Trade.status == "closed", Trade.pnl.isnot(None))
    rows   = closed.all()
    if not rows:
        return {"total": 0, "win_rate": 0, "total_pnl": 0, "avg_pnl": 0}
    pnls   = [r.pnl for r in rows]
    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    return {
        "total":         len(rows),
        "wins":          len(wins),
        "losses":        len(losses),
        "win_rate":      round(len(wins) / len(rows), 4),
        "total_pnl":     round(sum(pnls), 2),
        "avg_pnl":       round(sum(pnls) / len(pnls), 2),
        "avg_win":       round(sum(wins) / len(wins), 2) if wins else 0,
        "avg_loss":      round(sum(losses) / len(losses), 2) if losses else 0,
        "profit_factor": round(sum(wins) / (-sum(losses) + 1e-10), 3) if losses else 999,
    }


@router.get("/equity")
def equity_curve(db: Session = Depends(get_db)):
    rows = (
        db.query(Trade)
        .filter(Trade.status == "closed", Trade.pnl.isnot(None))
        .order_by(Trade.exit_time)
        .all()
    )
    cumulative = 0
    result = []
    for r in rows:
        cumulative += r.pnl
        result.append({
            "time":   r.exit_time.isoformat(),
            "pnl":    round(r.pnl, 2),
            "equity": round(1_000_000 + cumulative, 2),
        })
    return result
