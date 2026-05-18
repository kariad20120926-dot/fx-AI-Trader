# -*- coding: utf-8 -*-
"""
utils/line_notify.py — LINE Notify 通知クライアント
シグナル発生時に LINE にメッセージを送信する
"""
import requests
from utils.logger import get_logger

logger = get_logger(__name__)


class LineNotify:
    API_URL = "https://notify-api.line.me/api/notify"

    def __init__(self, token: str):
        self.token = token

    def send(self, message: str) -> bool:
        """
        LINE Notify にメッセージを送信する。
        Returns True if success, False if failed.
        """
        if not self.token:
            logger.warning("LINE Notify トークンが未設定です")
            return False
        try:
            res = requests.post(
                self.API_URL,
                headers={"Authorization": f"Bearer {self.token}"},
                data={"message": message},
                timeout=10,
            )
            if res.status_code == 200:
                logger.info("LINE Notify 送信成功")
                return True
            else:
                logger.error(f"LINE Notify 送信失敗: {res.status_code} {res.text}")
                return False
        except Exception as e:
            logger.error(f"LINE Notify エラー: {e}")
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
        """シグナル情報を整形して送信する"""
        direction = "🟢 BUY（買い）" if signal == "BUY" else "🔴 SELL（売り）"
        lines = [
            "",
            f"【FX AI Trader シグナル】",
            f"通貨ペア: {instrument}",
            f"シグナル: {direction}",
            f"信頼度: {confidence*100:.0f}%",
        ]
        if entry_price:
            lines.append(f"エントリー: {entry_price:.3f}")
        if stop_loss:
            lines.append(f"ストップロス: {stop_loss:.3f}")
        if take_profit:
            lines.append(f"テイクプロフィット: {take_profit:.3f}")
        if risk_reward:
            lines.append(f"RR比: {risk_reward:.2f}")

        return self.send("\n".join(lines))
