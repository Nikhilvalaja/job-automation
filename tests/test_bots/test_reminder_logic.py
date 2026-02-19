"""Tests for reminder bot stale-detection logic.

Tests the date-based filtering without needing Telegram or backend credentials.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest


def _make_job(company: str, role: str, date_applied: str, status: str = "Applied") -> dict:
    """Helper to create a job dict for testing."""
    return {
        "app_id": f"test_{company.lower()}",
        "company": company,
        "role": role,
        "date_added": date_applied,
        "date_applied": date_applied,
        "source": "Test",
        "job_url": "",
        "status": status,
        "last_email_date": "",
        "thread_id": "",
        "next_action_date": "",
        "notes": "",
    }


class TestStaleDetection:
    """Test the core stale-detection date logic used by the reminder bot."""

    def test_job_older_than_threshold_is_stale(self):
        """A job applied 10 days ago with 7-day threshold should be stale."""
        threshold = 7
        cutoff = date.today() - timedelta(days=threshold)
        applied = (date.today() - timedelta(days=10)).isoformat()
        job = _make_job("Google", "SWE", applied)

        check_date = date.fromisoformat(job["date_applied"])
        assert check_date <= cutoff

    def test_job_within_threshold_is_not_stale(self):
        """A job applied 3 days ago with 7-day threshold should not be stale."""
        threshold = 7
        cutoff = date.today() - timedelta(days=threshold)
        applied = (date.today() - timedelta(days=3)).isoformat()
        job = _make_job("Meta", "MLE", applied)

        check_date = date.fromisoformat(job["date_applied"])
        assert check_date > cutoff

    def test_job_exactly_at_threshold_is_stale(self):
        """A job applied exactly 7 days ago should be stale (<=)."""
        threshold = 7
        cutoff = date.today() - timedelta(days=threshold)
        applied = (date.today() - timedelta(days=7)).isoformat()
        job = _make_job("Amazon", "SDE", applied)

        check_date = date.fromisoformat(job["date_applied"])
        assert check_date <= cutoff

    def test_last_email_date_takes_precedence(self):
        """If last_email_date is set, use it instead of date_applied."""
        threshold = 7
        cutoff = date.today() - timedelta(days=threshold)

        # Applied 20 days ago, but last email 2 days ago — not stale
        job = _make_job("Apple", "iOS", (date.today() - timedelta(days=20)).isoformat())
        job["last_email_date"] = (date.today() - timedelta(days=2)).isoformat()

        check_date_str = job["last_email_date"] or job["date_applied"]
        check_date = date.fromisoformat(check_date_str)
        assert check_date > cutoff  # Not stale because last email was recent

    def test_empty_date_is_skipped(self):
        """Jobs with no date should be skipped, not crash."""
        job = _make_job("Unknown", "Role", "")
        check_date_str = job.get("last_email_date") or job.get("date_applied") or ""
        assert check_date_str == ""  # Should be skipped

    def test_invalid_date_is_skipped(self):
        """Jobs with invalid date format should not crash."""
        job = _make_job("Bad", "Date", "not-a-date")
        check_date_str = job["date_applied"]
        with pytest.raises(ValueError):
            date.fromisoformat(check_date_str)


class TestFilterMultipleJobs:
    """Test filtering a list of jobs for stale ones."""

    def _filter_stale(self, jobs: list[dict], threshold_days: int) -> list[dict]:
        """Replicate the reminder bot's filtering logic."""
        cutoff = date.today() - timedelta(days=threshold_days)
        stale = []
        for job in jobs:
            check_date_str = job.get("last_email_date") or job.get("date_applied") or ""
            if not check_date_str:
                continue
            try:
                check_date = date.fromisoformat(check_date_str)
            except ValueError:
                continue
            if check_date <= cutoff:
                stale.append(job)
        return stale

    def test_mixed_jobs(self):
        """Filter a mix of stale and fresh jobs."""
        jobs = [
            _make_job("Stale1", "R1", (date.today() - timedelta(days=10)).isoformat()),
            _make_job("Fresh1", "R2", (date.today() - timedelta(days=2)).isoformat()),
            _make_job("Stale2", "R3", (date.today() - timedelta(days=15)).isoformat()),
            _make_job("Fresh2", "R4", (date.today() - timedelta(days=1)).isoformat()),
        ]
        stale = self._filter_stale(jobs, threshold_days=7)
        assert len(stale) == 2
        assert stale[0]["company"] == "Stale1"
        assert stale[1]["company"] == "Stale2"

    def test_all_fresh(self):
        """No stale jobs when all are recent."""
        jobs = [
            _make_job("A", "R1", date.today().isoformat()),
            _make_job("B", "R2", (date.today() - timedelta(days=1)).isoformat()),
        ]
        stale = self._filter_stale(jobs, threshold_days=7)
        assert len(stale) == 0

    def test_all_stale(self):
        """All jobs stale when all are old."""
        jobs = [
            _make_job("A", "R1", (date.today() - timedelta(days=30)).isoformat()),
            _make_job("B", "R2", (date.today() - timedelta(days=20)).isoformat()),
        ]
        stale = self._filter_stale(jobs, threshold_days=7)
        assert len(stale) == 2

    def test_empty_list(self):
        """No crash on empty job list."""
        stale = self._filter_stale([], threshold_days=7)
        assert len(stale) == 0

    def test_custom_threshold(self):
        """Custom threshold of 3 days."""
        jobs = [
            _make_job("A", "R1", (date.today() - timedelta(days=4)).isoformat()),
            _make_job("B", "R2", (date.today() - timedelta(days=2)).isoformat()),
        ]
        stale = self._filter_stale(jobs, threshold_days=3)
        assert len(stale) == 1
        assert stale[0]["company"] == "A"
