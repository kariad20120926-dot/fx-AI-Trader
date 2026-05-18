# -*- coding: utf-8 -*-
import os
import uuid
from datetime import datetime, timezone, timedelta
from loguru import logger

WATCH_LIST = [
    {"instrument": "USD_JPY", "granularity": "H1"},
    {"instrument": "EUR_USD", "granularity": "H1"},
]

MARKET_OPEN_WEEKDAY  = 0
MARKET_CLOSE_WEEKDAY = 5
MARKET_OPEN_HOUR     = 6


def is_market_open() -> bool:
    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst)
    wd  = now.weekday()
    if wd == 6:
        return False
    if wd == 5 and now.hour >= MARKET_OPEN_HOUR:
        return False
    if wd == 0 and now.hour < MARKET_OPEN_HOUR:
        return False
    return True


def get_setting(key: str) -> str:
    """環境変数 → DB の順で設定値を取得する"""
    # 環境変数を優先（Cloud Run用）
    env_key = key.upper()
    val = os.environ.get(env_key, "")
    if val:
        return val
    # DBから取得（ローカル用）
    try:
        from data.database import SessionLocal, AppSetting
        db  = SessionLocal()
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        db.close()
        return row.value if row and row.value else ""
    except Exception:
        return ""


def get_notifiers() -> list:
    notifiers = []

    line_token = get_setting("line_notify_token")
    if line_token:
        try:
            from utils.line_notify import LineNotify
            notifiers.append(("line", LineNotify(line_token)))
            logger.debug("LINE通知 有効")
        except Exception as e:
            logger.warning(f"LINE初期化失敗: {e}")

    discord_url = get_setting("discord_webhook_url")
    if discord_url:
        try:
            from utils.discord_notify import DiscordNotify
            notifiers.append(("discord", DiscordNotify(discord_url)))
            logger.debug("Discord通知 有効")
        except Exception as e:
            logger.warning(f"Discord初期化失敗: {e}")

    return notifiers


def send_signal_notifications(notifiers: list, inst: str, trade) -> None:
    label_map = {1: "BUY", -1: "SELL", 0: "HOLD"}
    sig_label = label_map[trade.direction]
    for name, notifier in notifiers:
        try:
            notifier.send_signal(
                instrument=inst,
                signal=sig_label,
                confidence=trade.confidence,
                entry_price=trade.entry_price,
                stop_loss=trade.stop_loss,
                take_profit=trade.take_profit,
                risk_reward=trade.risk_reward,
            )
        except Exception as e:
            logger.error(f"{name}通知エラー: {e}")


def evaluate_open_trades(db, instrument: str, raw_data):
    from data.database import Trade
    open_trades = db.query(Trade).filter(Trade.instrument == instrument, Trade.status == "open").all()
    if not open_trades:
        return

    pip_mult = 100.0 if "JPY" in instrument else 10000.0

    for trade in open_trades:
        entry_time_utc = trade.entry_time.replace(tzinfo=timezone.utc)
        sub_df = raw_data[raw_data.index > entry_time_utc]

        for dt, row in sub_df.iterrows():
            high = row["high"]
            low = row["low"]
            
            exit_price = None
            exit_reason = None

            if trade.direction == "BUY":
                if low <= trade.stop_loss:
                    exit_price = trade.stop_loss
                    exit_reason = "SL"
                elif high >= trade.take_profit:
                    exit_price = trade.take_profit
                    exit_reason = "TP"
            elif trade.direction == "SELL":
                if high >= trade.stop_loss:
                    exit_price = trade.stop_loss
                    exit_reason = "SL"
                elif low <= trade.take_profit:
                    exit_price = trade.take_profit
                    exit_reason = "TP"

            if exit_price is not None:
                trade.exit_time = dt.replace(tzinfo=None)
                trade.exit_price = exit_price
                trade.exit_reason = exit_reason
                trade.status = "closed"
                
                diff = (exit_price - trade.entry_price) if trade.direction == "BUY" else (trade.entry_price - exit_price)
                trade.pnl_pips = diff * pip_mult
                trade.pnl = diff * trade.lot_size
                break
    db.commit()


async def run_signal_scan():
    from pathlib import Path
    from data.pipeline import DataPipeline, PipelineConfig
    from models.ensemble import EnsembleModel
    from strategies.signal_generator import SignalGenerator
    from data.database import SessionLocal, Signal, Trade

    if not is_market_open():
        jst = timezone(timedelta(hours=9))
        now = datetime.now(jst)
        logger.info(f"市場クローズ中のためスキップ ({now.strftime('%a %H:%M JST')})")
        return

    logger.info("シグナルスキャン開始")
    db        = SessionLocal()
    notifiers = get_notifiers()

    for watch in WATCH_LIST:
        inst, gran = watch["instrument"], watch["granularity"]
        try:
            model_path = Path(f"models/saved/{inst}/{gran}")
            if not model_path.exists():
                logger.warning(f"モデル未学習: {inst}/{gran}")
                continue

            model = EnsembleModel()
            model.load(model_path)

            # Twelve Data APIキーも環境変数から取得
            td_key = get_setting("twelvedata_api_key")
            source = "twelvedata" if td_key else "yahoo"

            pipe = DataPipeline(PipelineConfig(
                source=source,
                instrument=inst,
                granularity=gran,
                candle_count=600,
                drop_ohlcv=True,
            ))
            raw_data = pipe._fetch(count=600)
            if raw_data.empty:
                continue

            evaluate_open_trades(db, inst, raw_data)

            current_price = float(raw_data["close"].iloc[-1])
            cleaned  = pipe.preprocessor.clean(raw_data)
            features = pipe.feature_eng.generate(cleaned)
            if pipe.cfg.drop_ohlcv:
                ohlcv = ["open","high","low","close","volume"]
                features = features.drop(columns=[c for c in ohlcv if c in features.columns])
            X = features.dropna()

            if X.empty:
                continue

            sg    = SignalGenerator(model=model)
            trade = sg.generate_latest(X, current_price=current_price)
            info  = model.signal(X)

            label_map  = {1: "BUY", -1: "SELL", 0: "HOLD"}
            signal_str = label_map.get(info["raw_label"], "HOLD")
            
            sig_id = str(uuid.uuid4())
            ts_now = datetime.now(timezone.utc)

            row = Signal(
                id=sig_id,
                timestamp=ts_now,
                instrument=inst,
                granularity=gran,
                signal=signal_str if trade else "HOLD",
                confidence=info["confidence"],
                prob_buy=info["probabilities"].get("BUY"),
                prob_sell=info["probabilities"].get("SELL"),
                prob_hold=info["probabilities"].get("HOLD"),
                entry_price=trade.entry_price if trade else None,
                stop_loss=trade.stop_loss     if trade else None,
                take_profit=trade.take_profit if trade else None,
                lot_size=trade.lot_size       if trade else None,
                risk_reward=trade.risk_reward if trade else None,
                filtered=(trade is None and signal_str != "HOLD"),
            )
            db.add(row)

            if trade:
                trade_row = Trade(
                    id=str(uuid.uuid4()),
                    signal_id=sig_id,
                    instrument=inst,
                    granularity=gran,
                    direction=label_map[trade.direction],
                    entry_time=ts_now.replace(tzinfo=None),
                    entry_price=trade.entry_price,
                    stop_loss=trade.stop_loss,
                    take_profit=trade.take_profit,
                    lot_size=trade.lot_size,
                    confidence=info["confidence"],
                    status="open"
                )
                db.add(trade_row)

            db.commit()

            if trade:
                sig_label = label_map[trade.direction]
                logger.info(f"[{sig_label}] {inst}/{gran} entry={trade.entry_price:.4f}")
                send_signal_notifications(notifiers, inst, trade)
            else:
                logger.info(f"[HOLD] {inst}/{gran}")

        except Exception as e:
            logger.error(f"スキャンエラー ({inst}/{gran}): {e}")
            db.rollback()

    db.close()
    logger.info("シグナルスキャン完了")


async def run_weekly_retrain():
    import subprocess, sys
    logger.info("週次自動再学習開始")
    try:
        result = subprocess.run(
            [sys.executable, "retrain_best.py"],
            capture_output=True, text=True, timeout=3600
        )
        if result.returncode == 0:
            logger.info("週次再学習完了")
        else:
            logger.error(f"週次再学習失敗: {result.stderr[-500:]}")
    except Exception as e:
        logger.error(f"週次再学習エラー: {e}")


def register_jobs(scheduler) -> None:
    from apscheduler.triggers.cron import CronTrigger
    scheduler.add_job(
        run_signal_scan,
        CronTrigger(minute=1),
        id="scan_H1",
        name="H1シグナルスキャン",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_weekly_retrain,
        CronTrigger(day_of_week="sun", hour=2, minute=0),
        id="weekly_retrain",
        name="週次自動再学習",
        max_instances=1,
    )
    logger.info("スケジューラ登録完了")
