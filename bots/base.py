"""BaseBot — abstract base class for all bots.

Every bot inherits from this. Provides:
- httpx client for calling the backend API
- Structured logging
- start/stop lifecycle
- Error handling wrapper

SAFETY RULES (all bots MUST follow):
1. NEVER delete emails — only read and label
2. NEVER delete rows from Google Sheets — only update status (soft delete → Archived)
3. NEVER send emails on behalf of the user
4. NEVER modify email content or move emails between folders
5. NEVER store credentials in logs or error messages
6. ALL writes to Google Sheets go through the backend API (never direct)
7. ALL external API calls must use retry with backoff (never bare calls)
8. Bots must be idempotent — re-running produces the same result
9. Bots must log every action for auditability
10. Bots must fail gracefully — one bot crashing never affects others
"""

from __future__ import annotations

import abc
from typing import Any

import httpx

from src.config import get_settings
from src.utils.logging import get_logger


class BaseBot(abc.ABC):
    """Base class for all automation bots."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.logger = get_logger(f"bot.{name}")
        settings = get_settings()
        self.backend_url = settings.backend_url
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        """Lazy-initialized httpx client with sensible defaults."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                base_url=self.backend_url,
                timeout=30.0,
                headers={"Content-Type": "application/json"},
            )
        return self._client

    def start(self) -> None:
        """Initialize the bot. Override for custom startup logic."""
        self.logger.info(f"{self.name} bot started")

    def stop(self) -> None:
        """Clean up resources."""
        if self._client and not self._client.is_closed:
            self._client.close()
        self.logger.info(f"{self.name} bot stopped")

    @abc.abstractmethod
    def run_once(self) -> Any:
        """Execute one cycle of the bot's work. Must be implemented."""
        ...

    def run_safe(self) -> Any:
        """Run one cycle with error handling. Used by the orchestrator."""
        try:
            return self.run_once()
        except Exception as e:
            self.logger.error(f"{self.name} failed: {e}", exc_info=True)
            return None
