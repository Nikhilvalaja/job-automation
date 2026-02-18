"""Structured logging setup for the entire ecosystem.

Provides JSON-formatted logs with rotation. Every module gets its own
named logger via get_logger(name).

Usage:
    from src.utils.logging import get_logger
    logger = get_logger(__name__)
    logger.info("Bot started", extra={"bot": "email_bot"})
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from src.config import get_settings

_INITIALIZED = False


def setup_logging() -> None:
    """Initialize logging for the entire application. Safe to call multiple times."""
    global _INITIALIZED
    if _INITIALIZED:
        return
    _INITIALIZED = True

    settings = get_settings()
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    log_dir = settings.log_path

    # Root logger config
    root = logging.getLogger()
    root.setLevel(log_level)

    # Format: timestamp | level | logger_name | message
    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler (always)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(log_level)
    console.setFormatter(fmt)
    root.addHandler(console)

    # File handler (rotating, 10MB max, keep 5 backups)
    file_handler = logging.handlers.RotatingFileHandler(
        filename=log_dir / "job_automation.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # Error-only file (separate log for quick debugging)
    error_handler = logging.handlers.RotatingFileHandler(
        filename=log_dir / "errors.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(fmt)
    root.addHandler(error_handler)

    # Suppress noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a named logger. Auto-initializes logging on first call."""
    setup_logging()
    return logging.getLogger(name)
