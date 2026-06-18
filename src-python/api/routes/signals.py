# -*- coding: utf-8 -*-
from __future__ import annotations
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc

from data.database import get_db, Signal, init_db

router = APIRouter()
init_db()


class SignalOut(BaseModel):
    id:            str
    timestamp:     str
    instrument:    str
    granularity:   str
    signal:        str
    confidence:    float
    prob_buy:      Optional[float]
    prob_sell:     Optional[float]
    prob_hold:     Optional[float]
    entry_price:   Optional[float]
    stop_loss:     Optional[float]
    take_profit:   Optional[float]
    lot_size:      Optional[float]
    risk_reward:   Optional[float]
    filtered:      bool
    filter_reason: Optional[str]

    class Config:
        from_attributes = True


def to_jst_str(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    jst = timezone(timedelta(hours=9))
    dt_jst = dt.astimezone(jst)
    return dt_jst.strftime("%Y/%m/%d %H:%M")


def signal_to_dict(s: Signal, t: Optional[Trade] = None) -> dict:
    data = {
        "id":           s.id,
        "timestamp":    to_jst_str(s.timestamp),
        "instrument":   s.instrument,
        "granularity":  s.granularity,
        "signal":       s.signal,
        "confidence":   s.confidence,
        "prob_buy":     s.prob_buy,
        "prob_sell":    s.prob_sell,
        "prob_hold":    s.prob_hold,
        "entry_price":  s.entry_price,
        "stop_loss":    s.stop_loss,
        "take_profit":  s.take_profit,
        "lot_size":     s.lot_size,
        "risk_reward":  s.risk_reward,
        "filtered":     s.filtered or False,
        "filter_reason":s.filter_reason,
    }
    if t:
        data.update({
            "trade_status":  t.status,
            "exit_time":     to_jst_str(t.exit_time) if t.exit_time else None,
            "exit_price":    t.exit_price,
            "pnl_pips":      t.pnl_pips,
            "exit_reason":   t.exit_reason,
        })
    return data


@router.get("")
def list_signals(
    instrument: Optional[str] = Query(None),
    limit:      int           = Query(50, le=500),
    hours:      int           = Query(24),
    db: Session               = Depends(get_db),
):
    from data.database import Trade
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    q = db.query(Signal, Trade).outerjoin(Trade, Signal.id == Trade.signal_id).filter(Signal.timestamp >= since)
    if instrument:
        q = q.filter(Signal.instrument == instrument)
    rows = q.order_by(desc(Signal.timestamp)).limit(limit).all()
    return [signal_to_dict(s, t) for s, t in rows]


@router.get("/latest")
def latest_signals(db: Session = Depends(get_db)):
    instruments = [("USD_JPY", "H1"), ("EUR_USD", "H1"), ("GBP_USD", "H4")]
    results = []
    for inst, gran in instruments:
        row = (
            db.query(Signal)
            .filter(Signal.instrument == inst, Signal.granularity == gran)
            .order_by(desc(Signal.timestamp))
            .first()
        )
        if row:
            results.append(signal_to_dict(row))
    return results


@router.get("/calendar")
def economic_calendar(
    instrument: Optional[str] = Query(None),
    within_hours: float = Query(48.0, ge=1.0, le=168.0),
):
    """今後の高インパクト経済指標と現在のブラックアウト状態を返す"""
    try:
        from data.economic_calendar import EconomicCalendar
        cal = EconomicCalendar()
        events = cal.upcoming(instrument=instrument, within_hours=within_hours)
        blackout, label = (False, None)
        if instrument:
            blackout, label = cal.is_blackout(instrument)
        return {"events": events, "blackout": blackout, "blackout_event": label}
    except Exception as e:
        return {"events": [], "blackout": False, "blackout_event": None, "error": str(e)}


@router.post("/scan")
async def manual_scan():
    from api.scheduler import run_signal_scan
    import asyncio
    asyncio.create_task(run_signal_scan())
    return {"status": "scan started"}


@router.delete("/{signal_id}")
def delete_signal(signal_id: str, db: Session = Depends(get_db)):
    from fastapi import HTTPException
    from data.database import Trade
    row = db.query(Signal).filter(Signal.id == signal_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Signal not found")
    
    trade = db.query(Trade).filter(Trade.signal_id == signal_id).first()
    if trade:
        db.delete(trade)
        
    db.delete(row)
    db.commit()
    return {"status": "ok", "deleted": signal_id}
