"""Google Sheets client — centralized read/write access.

All Google Sheets operations go through this class. Provides retry logic,
connection management, and maps between Pydantic models and sheet rows.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

from src.config import get_settings
from src.models import JobCreate, JobResponse, JobStatus, JobUpdate
from src.sheets.schemas import COL, HEADERS, NUM_COLS
from src.utils.logging import get_logger
from src.utils.retry import retry

logger = get_logger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class SheetsClient:
    """Google Sheets client with connection pooling and retry logic."""

    def __init__(self) -> None:
        self._client: gspread.Client | None = None
        self._worksheet: gspread.Worksheet | None = None

    def _connect(self) -> gspread.Worksheet:
        """Establish or reuse connection to the worksheet."""
        if self._worksheet is not None:
            return self._worksheet

        settings = get_settings()
        creds = Credentials.from_service_account_file(
            str(settings.service_account_path),
            scopes=SCOPES,
        )
        self._client = gspread.authorize(creds)
        spreadsheet = self._client.open_by_key(settings.google_sheet_id)
        self._worksheet = spreadsheet.worksheet(settings.google_worksheet_name)

        # Ensure header row exists
        self._ensure_headers()
        logger.info("Connected to Google Sheets successfully")
        return self._worksheet

    def _ensure_headers(self) -> None:
        """Create header row if it doesn't exist."""
        ws = self._worksheet
        if ws is None:
            return
        first_row = ws.row_values(1)
        if not first_row or first_row != HEADERS:
            ws.update("A1", [HEADERS])
            logger.info("Header row created/updated in sheet")

    def _reconnect(self) -> gspread.Worksheet:
        """Force reconnect (e.g., after token expiry)."""
        self._client = None
        self._worksheet = None
        return self._connect()

    @property
    def ws(self) -> gspread.Worksheet:
        try:
            return self._connect()
        except gspread.exceptions.APIError:
            logger.warning("Sheets API error, reconnecting...")
            return self._reconnect()

    def is_connected(self) -> bool:
        """Check if we can reach the sheet."""
        try:
            self.ws.row_values(1)
            return True
        except Exception:
            return False

    @retry(max_attempts=3, base_delay=2.0, exceptions=(gspread.exceptions.APIError,))
    def get_all_jobs(self, status_filter: Optional[str] = None) -> list[JobResponse]:
        """Read all job rows from the sheet."""
        records = self.ws.get_all_records()
        jobs = []
        for record in records:
            if not record.get("app_id"):
                continue
            if status_filter and record.get("status") != status_filter:
                continue
            jobs.append(JobResponse(
                app_id=str(record.get("app_id", "")),
                date_added=str(record.get("date_added", "")),
                date_applied=str(record.get("date_applied", "")),
                company=str(record.get("company", "")),
                role=str(record.get("role", "")),
                source=str(record.get("source", "")),
                job_url=str(record.get("job_url", "")),
                status=JobStatus(record.get("status", "To Apply")),
                last_email_date=str(record.get("last_email_date", "")),
                thread_id=str(record.get("thread_id", "")),
                next_action_date=str(record.get("next_action_date", "")),
                notes=str(record.get("notes", "")),
            ))
        return jobs

    @retry(max_attempts=3, base_delay=2.0, exceptions=(gspread.exceptions.APIError,))
    def get_job(self, app_id: str) -> Optional[JobResponse]:
        """Get a single job by app_id."""
        cell = self.ws.find(app_id, in_column=COL["app_id"])
        if cell is None:
            return None
        row = self.ws.row_values(cell.row)
        # Pad row if shorter than expected
        row += [""] * (NUM_COLS - len(row))
        return JobResponse(
            app_id=row[COL["app_id"] - 1],
            date_added=row[COL["date_added"] - 1],
            date_applied=row[COL["date_applied"] - 1],
            company=row[COL["company"] - 1],
            role=row[COL["role"] - 1],
            source=row[COL["source"] - 1],
            job_url=row[COL["job_url"] - 1],
            status=JobStatus(row[COL["status"] - 1] or "To Apply"),
            last_email_date=row[COL["last_email_date"] - 1],
            thread_id=row[COL["thread_id"] - 1],
            next_action_date=row[COL["next_action_date"] - 1],
            notes=row[COL["notes"] - 1],
        )

    @retry(max_attempts=3, base_delay=2.0, exceptions=(gspread.exceptions.APIError,))
    def add_job(self, job: JobCreate) -> JobResponse:
        """Add a new job row to the sheet. Returns the created job."""
        app_id = uuid.uuid4().hex[:8]
        today = date.today().isoformat()
        date_applied = job.date_applied.isoformat() if job.date_applied else ""

        row = [
            app_id,
            today,
            date_applied,
            job.company,
            job.role,
            job.source,
            job.job_url,
            job.status.value,
            "",  # last_email_date
            "",  # thread_id
            "",  # next_action_date
            job.notes,
        ]
        self.ws.append_row(row, value_input_option="USER_ENTERED")
        logger.info(f"Added job: {app_id} — {job.company} / {job.role}")

        return JobResponse(
            app_id=app_id,
            date_added=today,
            date_applied=date_applied,
            company=job.company,
            role=job.role,
            source=job.source,
            job_url=job.job_url,
            status=job.status,
            last_email_date="",
            thread_id="",
            next_action_date="",
            notes=job.notes,
        )

    @retry(max_attempts=3, base_delay=2.0, exceptions=(gspread.exceptions.APIError,))
    def update_job(self, app_id: str, updates: JobUpdate) -> Optional[JobResponse]:
        """Update specific fields of a job row."""
        cell = self.ws.find(app_id, in_column=COL["app_id"])
        if cell is None:
            return None

        row_num = cell.row
        update_data = updates.model_dump(exclude_none=True)

        for field, value in update_data.items():
            if field not in COL:
                continue
            col_num = COL[field]
            if isinstance(value, (date, datetime)):
                value = value.isoformat()
            elif isinstance(value, JobStatus):
                value = value.value
            self.ws.update_cell(row_num, col_num, str(value))

        logger.info(f"Updated job {app_id}: {list(update_data.keys())}")
        return self.get_job(app_id)

    @retry(max_attempts=3, base_delay=2.0, exceptions=(gspread.exceptions.APIError,))
    def find_by_thread_id(self, thread_id: str) -> Optional[JobResponse]:
        """Find a job by Gmail thread ID."""
        cell = self.ws.find(thread_id, in_column=COL["thread_id"])
        if cell is None:
            return None
        row = self.ws.row_values(cell.row)
        row += [""] * (NUM_COLS - len(row))
        return JobResponse(
            app_id=row[COL["app_id"] - 1],
            date_added=row[COL["date_added"] - 1],
            date_applied=row[COL["date_applied"] - 1],
            company=row[COL["company"] - 1],
            role=row[COL["role"] - 1],
            source=row[COL["source"] - 1],
            job_url=row[COL["job_url"] - 1],
            status=JobStatus(row[COL["status"] - 1] or "To Apply"),
            last_email_date=row[COL["last_email_date"] - 1],
            thread_id=row[COL["thread_id"] - 1],
            next_action_date=row[COL["next_action_date"] - 1],
            notes=row[COL["notes"] - 1],
        )

    @retry(max_attempts=3, base_delay=2.0, exceptions=(gspread.exceptions.APIError,))
    def update_by_thread_id(self, thread_id: str, updates: JobUpdate) -> Optional[JobResponse]:
        """Update a job found by thread_id."""
        job = self.find_by_thread_id(thread_id)
        if job is None:
            return None
        return self.update_job(job.app_id, updates)
