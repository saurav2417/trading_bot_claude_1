"""Optional Telegram notifications. No-op unless configured."""

from __future__ import annotations

import logging

import requests

from ..config import Settings

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, settings: Settings):
        self.enabled = (
            bool(settings.notifications.get("telegram_enabled"))
            and bool(settings.telegram_bot_token)
            and bool(settings.telegram_chat_id)
        )
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id

    def send(self, message: str) -> None:
        if not self.enabled:
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": message[:4000]},
                timeout=10,
            )
        except requests.RequestException as exc:
            log.warning("telegram send failed: %s", exc)
