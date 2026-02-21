"""Centralized configuration for the entire job-automation ecosystem.

All settings are loaded from environment variables / .env file.
Uses pydantic-settings for validation and type coercion.
"""

from __future__ import annotations

from pathlib import Path
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# Project root = parent of src/
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Backend ---
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    debug: bool = False

    # --- Google Sheets ---
    google_service_account_file: str = "credentials/service_account.json"
    google_sheet_id: str = ""
    google_worksheet_name: str = "Applications"

    # --- Gmail API ---
    gmail_credentials_file: str = "credentials/gmail_credentials.json"
    gmail_token_file: str = "credentials/gmail_token.json"

    # --- Telegram ---
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # --- OpenAI ---
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # --- Scheduling ---
    email_bot_interval_minutes: int = 5
    reminder_bot_hour: int = 9
    reminder_bot_minute: int = 0
    discovery_bot_interval_minutes: int = 30
    followup_threshold_days: int = 7

    # --- Discovery Bot ---
    discovery_keywords: str = ""  # comma-separated: "software engineer,backend developer"
    discovery_locations: str = ""  # comma-separated: "remote,new york"
    discovery_excluded_keywords: str = ""  # comma-separated: "intern,director"

    # --- Alerts ---
    priority_score_threshold: float = 0.3    # Min match score (0.0-1.0) to send Telegram alert
    alert_quiet_hours_start: int = 22        # No alerts from this hour (24h clock, e.g. 22 = 10 PM)
    alert_quiet_hours_end: int = 8           # No alerts until this hour (e.g. 8 = 8 AM)

    # --- Logging ---
    log_level: str = "INFO"
    log_dir: str = "logs"

    # --- Derived ---
    @property
    def backend_url(self) -> str:
        return f"http://localhost:{self.backend_port}"

    @property
    def service_account_path(self) -> Path:
        path = Path(self.google_service_account_file)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    @property
    def gmail_credentials_path(self) -> Path:
        path = Path(self.gmail_credentials_file)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    @property
    def gmail_token_path(self) -> Path:
        path = Path(self.gmail_token_file)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    @property
    def log_path(self) -> Path:
        path = Path(self.log_dir)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings instance. Cached after first call."""
    return Settings()
