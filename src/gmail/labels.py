"""Gmail label management for the job automation bot.

Creates and manages labels under a "JobBot/" prefix so they're
easy to find and don't conflict with user labels.

SAFETY: Only creates and applies labels. Never deletes labels.
"""

from __future__ import annotations

from src.models import JobStatus
from src.utils.logging import get_logger
from src.utils.retry import retry

logger = get_logger(__name__)

# Label names for each status
LABEL_PREFIX = "JobBot"
STATUS_LABELS = {
    JobStatus.APPLIED: f"{LABEL_PREFIX}/Applied",
    JobStatus.ASSESSMENT: f"{LABEL_PREFIX}/Assessment",
    JobStatus.INTERVIEW: f"{LABEL_PREFIX}/Interview",
    JobStatus.REJECT: f"{LABEL_PREFIX}/Rejected",
    JobStatus.OFFER: f"{LABEL_PREFIX}/Offer",
}
PROCESSED_LABEL = f"{LABEL_PREFIX}/Processed"


class LabelManager:
    """Manages Gmail labels for the email bot."""

    def __init__(self, gmail_service) -> None:
        self._service = gmail_service
        self._label_cache: dict[str, str] = {}  # name -> label_id

    @retry(max_attempts=2, base_delay=1.0, exceptions=(Exception,))
    def ensure_labels_exist(self) -> dict[str, str]:
        """Create all JobBot labels if they don't exist. Returns name->id map."""
        existing = self._get_existing_labels()

        all_labels = list(STATUS_LABELS.values()) + [PROCESSED_LABEL]

        for label_name in all_labels:
            if label_name in existing:
                self._label_cache[label_name] = existing[label_name]
            else:
                label_id = self._create_label(label_name)
                self._label_cache[label_name] = label_id

        logger.info(f"Labels ready: {len(self._label_cache)} labels")
        return self._label_cache

    def get_label_id(self, label_name: str) -> str | None:
        """Get the label ID for a label name."""
        if not self._label_cache:
            self.ensure_labels_exist()
        return self._label_cache.get(label_name)

    def get_status_label_id(self, status: JobStatus) -> str | None:
        """Get the label ID for a job status."""
        label_name = STATUS_LABELS.get(status)
        if not label_name:
            return None
        return self.get_label_id(label_name)

    def get_processed_label_id(self) -> str:
        """Get the 'JobBot/Processed' label ID."""
        label_id = self.get_label_id(PROCESSED_LABEL)
        if not label_id:
            self.ensure_labels_exist()
            label_id = self._label_cache[PROCESSED_LABEL]
        return label_id

    def _get_existing_labels(self) -> dict[str, str]:
        """Fetch all existing labels. Returns name -> id map."""
        results = self._service.users().labels().list(userId="me").execute()
        labels = results.get("labels", [])
        return {label["name"]: label["id"] for label in labels}

    def _create_label(self, name: str) -> str:
        """Create a new Gmail label."""
        label_body = {
            "name": name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        }
        result = self._service.users().labels().create(
            userId="me", body=label_body
        ).execute()
        logger.info(f"Created Gmail label: {name}")
        return result["id"]
