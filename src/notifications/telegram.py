"""Telegram notification sender.

Sends formatted messages to a Telegram chat via the Bot API.
Used by the reminder bot and orchestrator for alerts.

SAFETY: Only sends messages to the configured chat. Never reads or deletes messages.
"""

from __future__ import annotations

import httpx

from src.config import get_settings
from src.notifications.base import NotificationChannel
from src.utils.logging import get_logger
from src.utils.retry import retry

logger = get_logger(__name__)


class TelegramNotifier(NotificationChannel):
    """Sends notifications via Telegram Bot API (sync, using httpx)."""

    def __init__(self) -> None:
        settings = get_settings()
        self._token = settings.telegram_bot_token
        self._chat_id = settings.telegram_chat_id
        self._base_url = f"https://api.telegram.org/bot{self._token}"

    def is_configured(self) -> bool:
        """Check if Telegram credentials are set."""
        return bool(self._token and self._chat_id)

    @retry(max_attempts=3, base_delay=2.0, exceptions=(httpx.HTTPError,))
    def send_message(self, text: str) -> bool:
        """Send a plain text message (Markdown supported)."""
        if not self.is_configured():
            logger.warning("Telegram not configured — skipping notification")
            return False

        resp = httpx.post(
            f"{self._base_url}/sendMessage",
            json={
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=15.0,
        )

        if resp.status_code == 200:
            logger.info("Telegram message sent successfully")
            return True
        else:
            logger.error(f"Telegram API error: {resp.status_code} — {resp.text}")
            return False

    def send_job_alert(self, job: dict, event: str) -> bool:
        """Send a formatted job status change alert."""
        company = job.get("company", "Unknown")
        role = job.get("role", "Unknown")
        status = job.get("status", "Unknown")
        app_id = job.get("app_id", "")

        text = (
            f"*{event}*\n\n"
            f"Company: {company}\n"
            f"Role: {role}\n"
            f"Status: {status}\n"
            f"ID: `{app_id}`"
        )
        return self.send_message(text)

    def send_summary(self, title: str, items: list[str]) -> bool:
        """Send a summary message with bullet points."""
        if not items:
            return self.send_message(f"*{title}*\n\nNo items to report.")

        bullets = "\n".join(f"• {item}" for item in items)
        text = f"*{title}*\n\n{bullets}\n\n_Total: {len(items)}_"
        return self.send_message(text)

    def send_followup_reminder(self, stale_jobs: list[dict]) -> bool:
        """Send a follow-up reminder for stale applications."""
        if not stale_jobs:
            return True  # Nothing to report

        items = []
        for job in stale_jobs:
            company = job.get("company", "?")
            role = job.get("role", "?")
            date_applied = job.get("date_applied", "?")
            items.append(f"{company} — {role} (applied {date_applied})")

        return self.send_summary(
            "Follow-Up Reminder — No Response",
            items,
        )
