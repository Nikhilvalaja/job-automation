"""Google Sheets column mapping and header definitions.

Single source of truth for the sheet structure. If columns change,
update only this file.
"""

from __future__ import annotations

# Header row (Row 1 in the Google Sheet)
HEADERS = [
    "app_id",
    "date_added",
    "date_applied",
    "company",
    "role",
    "source",
    "job_url",
    "status",
    "last_email_date",
    "thread_id",
    "next_action_date",
    "notes",
]

# Column index mapping (1-based for gspread)
COL = {name: idx + 1 for idx, name in enumerate(HEADERS)}

# Number of columns
NUM_COLS = len(HEADERS)
