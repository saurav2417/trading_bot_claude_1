"""Optional Telegram notifications. No-op unless configured."""

from __future__ import annotations

import logging

import requests

from ..config import Settings

log = logging.getLogger(__name__)


class Notifier:
    """Enabled automatically when bot token + chat id are present.

    Set `notifications.telegram_enabled: false` in settings.yaml to opt out
    even with credentials configured.
    """

    def __init__(self, settings: Settings):
        has_creds = bool(settings.telegram_bot_token) and bool(settings.telegram_chat_id)
        opted_out = settings.notifications.get("telegram_enabled") is False
        self.enabled = has_creds and not opted_out
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        if has_creds and opted_out:
            log.info("telegram credentials present but telegram_enabled=false; "
                     "notifications off")
        elif not has_creds:
            log.info("telegram not configured (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID "
                     "missing); notifications off")

    def send(self, message: str) -> None:
        if not self.enabled:
            return
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": message[:4000]},
                timeout=10,
            )
            if resp.status_code != 200:
                log.warning("telegram send failed (%s): %s — check that the chat id "
                            "is correct and you have /start-ed the bot",
                            resp.status_code, resp.text[:200])
        except requests.RequestException as exc:
            log.warning("telegram send failed: %s", exc)
