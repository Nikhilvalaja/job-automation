"""Shared test fixtures for the entire test suite."""

from __future__ import annotations

import pytest
from src.models import JobCreate, JobStatus


@pytest.fixture
def sample_job_create() -> JobCreate:
    return JobCreate(
        company="Google",
        role="Software Engineer",
        source="LinkedIn",
        job_url="https://careers.google.com/jobs/123",
        status=JobStatus.APPLIED,
        notes="Referred by John",
    )


@pytest.fixture
def sample_job_data() -> dict:
    return {
        "company": "Google",
        "role": "Software Engineer",
        "source": "LinkedIn",
        "job_url": "https://careers.google.com/jobs/123",
        "status": "Applied",
        "notes": "Referred by John",
    }


@pytest.fixture
def backend_url() -> str:
    return "http://localhost:8000"
