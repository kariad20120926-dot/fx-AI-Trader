# -*- coding: utf-8 -*-
"""
data/economic_calendar.py — 経済指標カレンダー（ファンダメンタルズフィルター）

ForexFactory の無料カレンダーフィード（今週+来週）を取得・キャッシュし、
高インパクト指標の発表前後のブラックアウト時間帯を判定する。

FOMC・雇用統計・CPI などの発表直前直後はスプレッド拡大とランダムな
急変動でテクニカル予測の精度が大きく落ちるため、その時間帯の新規
エントリーを抑止することで実運用の期待値を改善する。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from utils.logger import get_logger

logger = get_logger(__name__)

FEED_URLS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
]

CACHE_FILE = Path(__file__).parent / "cache" / "economic_calendar.json"

# インパクト強度の序列
_IMPACT_RANK = {"Holiday": 0, "Low": 1, "Medium": 2, "High": 3}


class EconomicCalendar:
    """
    経済指標カレンダーの取得・キャッシュ・ブラックアウト判定。

    Parameters
    ----------
    blackout_before_min : 指標発表の何分前から新規エントリーを止めるか
    blackout_after_min  : 発表の何分後まで止めるか
    min_impact          : ブラックアウト対象の最小インパクト ("High" | "Medium")
    cache_ttl_min       : キャッシュの有効期間（分）
    """

    def __init__(
        self,
        blackout_before_min: int = 30,
        blackout_after_min:  int = 30,
        min_impact:          str = "High",
        cache_ttl_min:       int = 60,
        cache_file:          Optional[Path] = None,
    ):
        self.before  = timedelta(minutes=blackout_before_min)
        self.after   = timedelta(minutes=blackout_after_min)
        self.min_rank = _IMPACT_RANK.get(min_impact, 3)
        self.cache_ttl = timedelta(minutes=cache_ttl_min)
        self.cache_file = cache_file or CACHE_FILE
        self._events: list[dict] = []
        self._loaded_at: Optional[datetime] = None
        self._next_retry: Optional[datetime] = None   # 取得失敗後のクールダウン

    # ─────────────────────────────────────────────────────────────────────────

    def refresh(self, force: bool = False) -> bool:
        """
        フィードを取得してキャッシュを更新する。
        ネットワーク失敗時は古いキャッシュにフォールバック（フェイルオープン）。
        """
        now = datetime.now(timezone.utc)
        if not force and self._loaded_at and (now - self._loaded_at) < self.cache_ttl:
            return True

        # 直近の取得失敗から5分間は再試行しない（フィードのレート制限対策。
        # スキャンは毎分走るため、これが無いと 429 が永続する）
        if not force and self._next_retry and now < self._next_retry:
            return bool(self._events)

        # 1. ディスクキャッシュが新しければそれを使う
        cached = self._read_cache()
        if not force and cached is not None:
            fetched_at, events = cached
            if (now - fetched_at) < self.cache_ttl:
                self._events, self._loaded_at = events, fetched_at
                return True

        # 2. ネットワーク取得（フィード単位の失敗は許容し、全滅時のみ失敗扱い）
        try:
            from utils.ssl_trust import ensure_truststore
            ensure_truststore()
            import requests
            events: list[dict] = []
            fetched = 0
            for url in FEED_URLS:
                try:
                    resp = requests.get(url, timeout=15)
                    resp.raise_for_status()
                    events.extend(resp.json())
                    fetched += 1
                except Exception as fe:
                    logger.warning(f"フィード取得失敗 ({url}): {fe}")
            if fetched == 0:
                raise RuntimeError("全フィードの取得に失敗")
            self._events    = self._parse(events)
            self._loaded_at = now
            self._write_cache(now)
            logger.info(f"経済カレンダー更新: {len(self._events)}件 ({fetched}/{len(FEED_URLS)}フィード)")
            return True
        except Exception as e:
            logger.warning(f"経済カレンダー取得失敗: {e}")
            self._next_retry = now + timedelta(minutes=5)
            if cached is not None:
                fetched_at, events = cached
                self._events, self._loaded_at = events, fetched_at
                logger.info(f"古いキャッシュを使用 ({fetched_at:%m/%d %H:%M} 取得, {len(events)}件)")
                return True
            return False

    def is_blackout(
        self,
        instrument: str,
        at: Optional[datetime] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        指定時刻（デフォルト=現在）が対象通貨の高インパクト指標の
        ブラックアウト時間帯かを判定する。

        Returns
        -------
        (True, "USD: CPI y/y (06/15 21:30 UTC)") | (False, None)
        """
        self.refresh()
        at = at or datetime.now(timezone.utc)
        currencies = set(instrument.upper().replace("/", "_").split("_")) | {"ALL"}

        for ev in self._events:
            if ev["rank"] < self.min_rank:
                continue
            if ev["country"].upper() not in currencies:
                continue
            if ev["time"] - self.before <= at <= ev["time"] + self.after:
                label = f"{ev['country']}: {ev['title']} ({ev['time']:%m/%d %H:%M} UTC)"
                return True, label
        return False, None

    def upcoming(
        self,
        instrument: Optional[str] = None,
        within_hours: float = 24.0,
    ) -> list[dict]:
        """今後 within_hours 時間以内の対象イベント一覧（UI・通知用）"""
        self.refresh()
        now = datetime.now(timezone.utc)
        horizon = now + timedelta(hours=within_hours)
        currencies = None
        if instrument:
            currencies = set(instrument.upper().replace("/", "_").split("_")) | {"ALL"}

        out = []
        for ev in self._events:
            if ev["rank"] < self.min_rank:
                continue
            if not (now <= ev["time"] <= horizon):
                continue
            if currencies and ev["country"].upper() not in currencies:
                continue
            out.append({
                "time":    ev["time"].isoformat(),
                "country": ev["country"],
                "title":   ev["title"],
                "impact":  ev["impact"],
                "forecast": ev.get("forecast", ""),
                "previous": ev.get("previous", ""),
            })
        return sorted(out, key=lambda e: e["time"])

    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse(raw: list[dict]) -> list[dict]:
        events = []
        for ev in raw:
            try:
                t = datetime.fromisoformat(ev["date"]).astimezone(timezone.utc)
            except (KeyError, ValueError):
                continue
            impact = ev.get("impact", "Low")
            events.append({
                "time":     t,
                "country":  ev.get("country", ""),
                "title":    ev.get("title", ""),
                "impact":   impact,
                "rank":     _IMPACT_RANK.get(impact, 1),
                "forecast": ev.get("forecast", ""),
                "previous": ev.get("previous", ""),
            })
        return events

    def _read_cache(self) -> Optional[tuple[datetime, list[dict]]]:
        try:
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
            fetched_at = datetime.fromisoformat(data["fetched_at"])
            events = []
            for ev in data["events"]:
                ev = dict(ev)
                ev["time"] = datetime.fromisoformat(ev["time"])
                events.append(ev)
            return fetched_at, events
        except Exception:
            return None

    def _write_cache(self, fetched_at: datetime) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "fetched_at": fetched_at.isoformat(),
                "events": [
                    {**ev, "time": ev["time"].isoformat()} for ev in self._events
                ],
            }
            self.cache_file.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"カレンダーキャッシュ保存失敗: {e}")
