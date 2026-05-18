# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from data.database import get_db, AppSetting, init_db

router = APIRouter()
init_db()

DEFAULTS = {
    "oanda_api_key":       "",
    "oanda_account_id":    "",
    "oanda_environment":   "practice",
    "twelvedata_api_key":  "",
    "trade_symbol":        "USD_JPY",
    "trade_timeframe":     "H1",
    "risk_per_trade":      "0.02",
    "sl_atr_mult":         "2.0",
    "tp_atr_mult":         "3.0",
    "confidence_min":      "0.33",
    "adx_min":             "0.0",
    "initial_capital":     "1000000",
    "line_notify_token":   "",
    "discord_webhook_url": "",
}


class SettingsPayload(BaseModel):
    data: dict


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    rows   = db.query(AppSetting).all()
    result = dict(DEFAULTS)
    for r in rows:
        result[r.key] = r.value
    # マスク
    for key in ["oanda_api_key", "twelvedata_api_key"]:
        if result.get(key):
            v = result[key]
            result[f"{key}_masked"] = v[:4] + "****" + v[-4:] if len(v) > 8 else "****"
    return result


@router.put("")
def save_settings(payload: SettingsPayload, db: Session = Depends(get_db)):
    for key, value in payload.data.items():
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row:
            row.value = str(value)
        else:
            db.add(AppSetting(key=key, value=str(value)))
    db.commit()
    return {"status": "saved"}


@router.post("/test")
def test_connection(db: Session = Depends(get_db)):
    rows       = {r.key: r.value for r in db.query(AppSetting).all()}
    api_key    = rows.get("oanda_api_key", "")
    account_id = rows.get("oanda_account_id", "")
    env        = rows.get("oanda_environment", "practice")
    if not api_key or not account_id:
        return {"success": False, "message": "APIキーまたはアカウントIDが未設定です"}
    try:
        import oandapyV20
        import oandapyV20.endpoints.accounts as accounts
        client = oandapyV20.API(access_token=api_key, environment=env)
        r      = accounts.AccountSummary(account_id)
        client.request(r)
        balance = r.response["account"]["balance"]
        return {"success": True, "message": f"接続成功 残高: {float(balance):,.0f}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/test-twelvedata")
def test_twelvedata(db: Session = Depends(get_db)):
    rows   = {r.key: r.value for r in db.query(AppSetting).all()}
    api_key = rows.get("twelvedata_api_key", "")
    if not api_key:
        return {"success": False, "message": "Twelve Data APIキーが未設定です"}
    try:
        from data.twelvedata_client import TwelveDataClient
        client = TwelveDataClient(api_key)
        price  = client.get_price("USD_JPY")
        return {"success": True, "message": f"接続成功 USD/JPY: {price:.3f}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/test-discord")
def test_discord(db: Session = Depends(get_db)):
    rows = {r.key: r.value for r in db.query(AppSetting).all()}
    url  = rows.get("discord_webhook_url", "")
    if not url:
        return {"success": False, "message": "Discord Webhook URLが未設定です"}
    try:
        from utils.discord_notify import DiscordNotify
        discord = DiscordNotify(url)
        success = discord.send(content="**FX AI Trader** — Discord通知テスト成功！")
        return {"success": success, "message": "送信成功" if success else "送信失敗"}
    except Exception as e:
        return {"success": False, "message": str(e)}
