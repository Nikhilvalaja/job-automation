"""Gmail service factory — wraps multi_account for single-account usage.

Provides get_gmail_service() for Account 1 (nikhilvalaja@gmail.com).
"""

from __future__ import annotations

from src.gmail.multi_account import get_account1_service


def get_gmail_service():
    """Return Gmail API service for Account 1 (nikhilvalaja@gmail.com)."""
    return get_account1_service()
