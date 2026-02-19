"""Tests for the jobs CRUD router.

Uses a mock SheetsClient so tests run without Google credentials.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.dependencies import get_sheets_client
from backend.main import app
from src.models import JobResponse, JobStatus, JobUpdate


# ---------------------------------------------------------------------------
# Mock SheetsClient that stores data in-memory
# ---------------------------------------------------------------------------

class FakeSheetsClient:
    """In-memory replacement for SheetsClient for testing."""

    def __init__(self) -> None:
        self._jobs: dict[str, JobResponse] = {}
        self._counter = 0

    def is_connected(self) -> bool:
        return True

    def add_job(self, job):
        self._counter += 1
        app_id = f"test{self._counter:04d}"
        from datetime import date
        resp = JobResponse(
            app_id=app_id,
            date_added=date.today().isoformat(),
            date_applied=job.date_applied.isoformat() if job.date_applied else "",
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
        self._jobs[app_id] = resp
        return resp

    def get_all_jobs(self, status_filter=None):
        jobs = list(self._jobs.values())
        if status_filter:
            jobs = [j for j in jobs if j.status.value == status_filter]
        return jobs

    def get_job(self, app_id):
        return self._jobs.get(app_id)

    def update_job(self, app_id, updates):
        job = self._jobs.get(app_id)
        if job is None:
            return None
        data = job.model_dump()
        for field, value in updates.model_dump(exclude_none=True).items():
            if field in data:
                data[field] = value
        updated = JobResponse(**data)
        self._jobs[app_id] = updated
        return updated

    def find_by_thread_id(self, thread_id):
        for job in self._jobs.values():
            if job.thread_id == thread_id:
                return job
        return None

    def update_by_thread_id(self, thread_id, updates):
        job = self.find_by_thread_id(thread_id)
        if job is None:
            return None
        return self.update_job(job.app_id, updates)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_sheets():
    return FakeSheetsClient()


@pytest.fixture
def client(fake_sheets):
    """TestClient with mocked SheetsClient."""
    app.dependency_overrides[get_sheets_client] = lambda: fake_sheets
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCreateJob:
    def test_create_returns_201(self, client):
        resp = client.post("/jobs", json={
            "company": "Google",
            "role": "SWE",
            "source": "LinkedIn",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["company"] == "Google"
        assert data["role"] == "SWE"
        assert data["app_id"].startswith("test")

    def test_create_with_all_fields(self, client):
        resp = client.post("/jobs", json={
            "company": "Meta",
            "role": "MLE",
            "source": "Referral",
            "job_url": "https://meta.com/jobs/456",
            "status": "Applied",
            "notes": "Friend works there",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "Applied"
        assert data["notes"] == "Friend works there"

    def test_create_missing_required_fields(self, client):
        resp = client.post("/jobs", json={"company": "Google"})
        assert resp.status_code == 422  # Validation error


class TestListJobs:
    def test_list_empty(self, client):
        resp = client.get("/jobs")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_list_after_create(self, client):
        client.post("/jobs", json={"company": "A", "role": "R1"})
        client.post("/jobs", json={"company": "B", "role": "R2"})
        resp = client.get("/jobs")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    def test_list_with_status_filter(self, client):
        client.post("/jobs", json={"company": "A", "role": "R1", "status": "Applied"})
        client.post("/jobs", json={"company": "B", "role": "R2", "status": "To Apply"})
        resp = client.get("/jobs", params={"status": "Applied"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["jobs"][0]["company"] == "A"


class TestGetJob:
    def test_get_existing(self, client):
        create_resp = client.post("/jobs", json={"company": "X", "role": "Y"})
        app_id = create_resp.json()["app_id"]
        resp = client.get(f"/jobs/{app_id}")
        assert resp.status_code == 200
        assert resp.json()["company"] == "X"

    def test_get_not_found(self, client):
        resp = client.get("/jobs/nonexistent")
        assert resp.status_code == 404


class TestUpdateJob:
    def test_update_status(self, client):
        create_resp = client.post("/jobs", json={"company": "A", "role": "B"})
        app_id = create_resp.json()["app_id"]
        resp = client.patch(f"/jobs/{app_id}", json={"status": "Interview"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "Interview"

    def test_update_not_found(self, client):
        resp = client.patch("/jobs/fake123", json={"status": "Applied"})
        assert resp.status_code == 404

    def test_update_notes(self, client):
        create_resp = client.post("/jobs", json={"company": "A", "role": "B"})
        app_id = create_resp.json()["app_id"]
        resp = client.patch(f"/jobs/{app_id}", json={"notes": "Phone screen done"})
        assert resp.status_code == 200
        assert resp.json()["notes"] == "Phone screen done"


class TestUpdateByThread:
    def test_update_by_thread_not_found(self, client):
        resp = client.patch("/jobs/by-thread/thread123", json={"status": "Interview"})
        assert resp.status_code == 404


class TestDeleteJob:
    def test_delete_archives(self, client):
        create_resp = client.post("/jobs", json={"company": "Del", "role": "Me"})
        app_id = create_resp.json()["app_id"]
        resp = client.delete(f"/jobs/{app_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "Archived"

    def test_delete_not_found(self, client):
        resp = client.delete("/jobs/fake999")
        assert resp.status_code == 404
