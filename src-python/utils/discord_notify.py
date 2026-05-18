# -*- coding: utf-8 -*-
"""
utils/discord_notify.py — Discord Webhook 通知クライアント
シグナル発生時に Discord チャンネルに通知を送信する
"""
import requests
from utils.logger import get_logger

logger = get_logger(__name__)


class DiscordNotify:

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, content: str = None, embeds: list = None) -> bool:
        if not self.webhook_url:
            logger.warning("Discord Webhook URLが未設定です")
            return False
        try:
            payload = {}
            if content:
                payload["content"] = content
            if embeds:
                payload["embeds"] = embeds

            res = requests.post(
                self.webhook_url,
                json=payload,
                timeout=10,
            )
            if res.status_code in (200, 204):
                logger.info("Discord通知送信成功")
                return True
            else:
                logger.error(f"Discord通知失敗: {res.status_code} {res.text}")
                return False
        except Exception as e:
            logger.error(f"Discord通知エラー: {e}")
            return False

    def send_signal(
        self,
        instrument:  str,
        signal:      str,
        confidence:  float,
        entry_price: float = None,
        stop_loss:   float = None,
        take_profit: float = None,
        risk_reward: float = None,
    ) -> bool:
        color  = 0x27c87a if signal == "BUY" else 0xf05a5a
        emoji  = "🟢" if signal == "BUY" else "🔴"
        action = "買い" if signal == "BUY" else "売り"

        fields = [
            {"name": "シグナル", "value": f"{emoji} **{signal}**（{action}）", "inline": True},
            {"name": "信頼度",   "value": f"{confidence*100:.0f}%",            "inline": True},
        ]
        if entry_price:
            fields.append({"name": "エントリー", "value": f"{entry_price:.3f}", "inline": True})
        if stop_loss:
            fields.append({"name": "ストップロス 🔴", "value": f"{stop_loss:.3f}", "inline": True})
        if take_profit:
            fields.append({"name": "テイクプロフィット 🟢", "value": f"{take_profit:.3f}", "inline": True})
        if risk_reward:
            fields.append({"name": "RR比", "value": f"{risk_reward:.2f}", "inline": True})

        embed = {
            "title":       f"FX AI Trader — {instrument} シグナル",
            "color":       color,
            "fields":      fields,
            "footer":      {"text": "FX AI Trader"},
        }
        return self.send(embeds=[embed])
