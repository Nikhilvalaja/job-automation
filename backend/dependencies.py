"""FastAPI dependency injection.

Provides shared instances (SheetsClient, etc.) to route handlers.
"""

from __future__ import annotations

from functools import lru_cache

from src.sheets.client import SheetsClient


@lru_cache(maxsize=1)
def get_sheets_client() -> SheetsClient:
    """Singleton SheetsClient instance."""
    return SheetsClient()
