"""Multi-account Gmail client — supports monitoring multiple Gmail accounts.

Account 1: nikhilvalaja@gmail.com (primary)
Account 2: valajashekarnikhil12@gmail.com (secondary)

Both accounts are monitored for:
- Job application confirmations
- Interview requests
- Rejection emails
- LinkedIn job alert emails
- Indeed job alert emails
- Dice job alert emails

SAFETY: Read-only + labels only. Never sends, deletes, or modifies emails.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from src.utils.logging import get_logger

logger = get_logger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.modify",
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _authenticate(creds_file: str, token_file: str) -> Any:
    """Authenticate a Gmail account and return a service object."""
    creds_path = PROJECT_ROOT / creds_file
    token_path = PROJECT_ROOT / token_file

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        if not creds_path.exists():
            raise FileNotFoundError(
                f"Gmail credentials not found at {creds_path}\n"
                "Download from Google Cloud Console → APIs & Services → Credentials"
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
        creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())
        logger.info(f"Saved token to {token_path}")

    return build("gmail", "v1", credentials=creds)


def get_account1_service() -> Any:
    """Get Gmail service for nikhilvalaja@gmail.com"""
    from dotenv import load_dotenv
    load_dotenv()
    creds = os.getenv("GMAIL_CREDENTIALS_FILE", "credentials/gmail_credentialsss.json")
    token = os.getenv("GMAIL_TOKEN_FILE", "credentials/gmail_token.json")
    return _authenticate(creds, token)


def get_account2_service() -> Any:
    """Get Gmail service for valajashekarnikhil12@gmail.com"""
    from dotenv import load_dotenv
    load_dotenv()
    creds = os.getenv("GMAIL2_CREDENTIALS_FILE", "credentials/gmail_credentialsss.json")
    token = os.getenv("GMAIL2_TOKEN_FILE", "credentials/gmail_token2.json")
    return _authenticate(creds, token)


def get_all_services() -> list[tuple[str, Any]]:
    """Return all configured Gmail accounts as (email_hint, service) pairs."""
    services = []
    try:
        svc1 = get_account1_service()
        services.append(("nikhilvalaja@gmail.com", svc1))
        logger.info("Account 1 (nikhilvalaja@gmail.com) connected")
    except Exception as e:
        logger.warning(f"Account 1 connection failed: {e}")

    from dotenv import load_dotenv
    load_dotenv()
    if os.getenv("GMAIL2_ENABLED", "false").lower() == "true":
        try:
            svc2 = get_account2_service()
            services.append(("valajashekarnikhil12@gmail.com", svc2))
            logger.info("Account 2 (valajashekarnikhil12@gmail.com) connected")
        except Exception as e:
            logger.warning(f"Account 2 not yet authenticated. Run: python -m src.gmail.setup_account2\nError: {e}")

    return services


def search_emails(service: Any, query: str, max_results: int = 50) -> list[dict]:
    """Search Gmail for messages matching query."""
    try:
        result = service.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()
        messages = result.get("messages", [])
        full = []
        for msg in messages[:max_results]:
            detail = service.users().messages().get(
                userId="me", id=msg["id"], format="full"
            ).execute()
            full.append(detail)
        return full
    except Exception as e:
        logger.error(f"Gmail search failed: {e}")
        return []
