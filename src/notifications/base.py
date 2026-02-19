"""Abstract base for notification channels.

All notification providers (Telegram, Slack, Discord, etc.) implement this.
"""

from __future__ import annotations

import abc
from typing import Any


class NotificationChannel(abc.ABC):
    """Base class for all notification channels."""

    @abc.abstractmethod
    def send_message(self, text: str) -> bool:
        """Send a plain text message. Returns True if successful."""
        ...

    @abc.abstractmethod
    def send_job_alert(self, job: dict, event: str) -> bool:
        """Send a formatted job status alert. Returns True if successful."""
        ...

    @abc.abstractmethod
    def send_summary(self, title: str, items: list[str]) -> bool:
        """Send a summary with a title and bullet points. Returns True if successful."""
        ...

    @abc.abstractmethod
    def is_configured(self) -> bool:
        """Check if this channel has valid credentials configured."""
        ...
