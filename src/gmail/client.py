"""Gmail API client — OAuth 2.0 Desktop flow.

Provides read-only access to Gmail for monitoring job-related emails.
SAFETY: Never deletes, sends, or modifies emails. Only reads and labels.
"""

from __future__ import annotations

import base64
import re
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from src.config import get_settings
from src.utils.logging import get_logger
from src.utils.retry import retry

logger = get_logger(__name__)

# Read-only + labels. We NEVER request send/delete/modify scopes.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.modify",  # needed for applying labels
]


class GmailClient:
    """Gmail API client with OAuth 2.0 token management.

    SAFETY: This client only reads emails and applies labels.
    It NEVER deletes, sends, or modifies email content.
    """

    def __init__(self) -> None:
        self._service = None
        self._creds: Credentials | None = None

    def _authenticate(self) -> Credentials:
        """Load or refresh OAuth credentials. Opens browser on first run."""
        settings = get_settings()
        creds_path = settings.gmail_credentials_path
        token_path = settings.gmail_token_path

        creds = None

        # Load existing token
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        # Refresh or re-authenticate
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing Gmail OAuth token...")
            creds.refresh(Request())
        elif not creds or not creds.valid:
            if not creds_path.exists():
                raise FileNotFoundError(
                    f"Gmail credentials not found at {creds_path}. "
                    "Download OAuth credentials from Google Cloud Console."
                )
            logger.info("Starting Gmail OAuth flow (browser will open)...")
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)

        # Save token for next time
        token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

        self._creds = creds
        return creds

    @property
    def service(self):
        """Lazy-initialized Gmail API service."""
        if self._service is None:
            creds = self._authenticate()
            self._service = build("gmail", "v1", credentials=creds)
            logger.info("Gmail API client initialized")
        return self._service

    @retry(max_attempts=3, base_delay=2.0, exceptions=(Exception,))
    def get_recent_messages(
        self,
        query: str = "is:inbox",
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        """Fetch recent messages matching a query.

        Args:
            query: Gmail search query (e.g., "is:inbox newer_than:1h")
            max_results: Maximum number of messages to return.

        Returns:
            List of message dicts with id, threadId, snippet, subject, from, date.
        """
        results = (
            self.service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )

        messages = results.get("messages", [])
        if not messages:
            return []

        detailed = []
        for msg_stub in messages:
            detail = self.get_message_detail(msg_stub["id"])
            if detail:
                detailed.append(detail)

        return detailed

    @retry(max_attempts=3, base_delay=1.0, exceptions=(Exception,))
    def get_message_detail(self, msg_id: str) -> Optional[dict[str, Any]]:
        """Get full details for a single message."""
        msg = (
            self.service.users()
            .messages()
            .get(userId="me", id=msg_id, format="full")
            .execute()
        )

        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}

        # Extract body text
        body = self._extract_body(msg["payload"])

        return {
            "id": msg["id"],
            "thread_id": msg["threadId"],
            "subject": headers.get("subject", ""),
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "date": headers.get("date", ""),
            "snippet": msg.get("snippet", ""),
            "body": body,
            "label_ids": msg.get("labelIds", []),
        }

    def _extract_body(self, payload: dict) -> str:
        """Extract plain text body from message payload."""
        body_text = ""

        if payload.get("body", {}).get("data"):
            body_text = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

        # Check parts (multipart messages)
        for part in payload.get("parts", []):
            mime = part.get("mimeType", "")
            if mime == "text/plain" and part.get("body", {}).get("data"):
                body_text = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                break
            elif mime.startswith("multipart/"):
                # Recurse into nested parts
                body_text = self._extract_body(part)
                if body_text:
                    break

        return body_text[:5000]  # Cap body length to prevent memory issues

    @retry(max_attempts=3, base_delay=1.0, exceptions=(Exception,))
    def get_thread(self, thread_id: str) -> list[dict[str, Any]]:
        """Get all messages in a thread."""
        thread = (
            self.service.users()
            .threads()
            .get(userId="me", id=thread_id, format="full")
            .execute()
        )

        messages = []
        for msg in thread.get("messages", []):
            headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
            messages.append({
                "id": msg["id"],
                "thread_id": msg["threadId"],
                "subject": headers.get("subject", ""),
                "from": headers.get("from", ""),
                "date": headers.get("date", ""),
                "snippet": msg.get("snippet", ""),
            })

        return messages

    @retry(max_attempts=2, base_delay=1.0, exceptions=(Exception,))
    def apply_label(self, msg_id: str, label_id: str) -> None:
        """Apply a label to a message. SAFETY: only adds labels, never removes."""
        self.service.users().messages().modify(
            userId="me",
            id=msg_id,
            body={"addLabelIds": [label_id]},
        ).execute()
        logger.info(f"Applied label {label_id} to message {msg_id}")

    def is_connected(self) -> bool:
        """Check if we can reach Gmail API."""
        try:
            self.service.users().getProfile(userId="me").execute()
            return True
        except Exception:
            return False
