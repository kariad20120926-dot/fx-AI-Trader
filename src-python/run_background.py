# -*- coding: utf-8 -*-
"""
run_background.py — バックグラウンド専用スキャナー
アプリを閉じていても毎時シグナルスキャン + LINE/Discord通知を実行する
Windowsタスクスケジューラから起動する

使い方:
  python run_background.py
"""
import sys
import os
import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path

# src-python をパスに追加
BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

from loguru import logger
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

logger.add(
    BASE / "logs" / "scanner.log",
    rotation="1 week",
    retention="1 month",
    level="INFO",
    encoding="utf-8",
)


def sync_scan():
    """同期ラッパー（タスクスケジューラから呼ばれる）"""
    from api.scheduler import run_signal_scan
    asyncio.run(run_signal_scan())


def main():
    logger.info("=" * 50)
    logger.info("FX AI Trader バックグラウンドスキャナー起動")
    logger.info(f"起動時刻: {datetime.now(timezone.utc)}")
    logger.info("=" * 50)

    # 起動直後に1回スキャン
    logger.info("初回スキャン実行...")
    sync_scan()

    # 毎時1分にスキャン
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        sync_scan,
        CronTrigger(minute=1),
        id="scan",
        name="毎時スキャン",
        max_instances=1,
        coalesce=True,
    )

    logger.info("スケジューラ起動（毎時1分にスキャン）")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("スキャナー停止")


if __name__ == "__main__":
    # logs フォルダ作成
    (BASE / "logs").mkdir(exist_ok=True)
    main()
