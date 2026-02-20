"""Tests for the analysis API router — resume CRUD, JD normalization, scoring."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.analysis import router


@pytest.fixture
def app():
    _app = FastAPI()
    _app.include_router(router)
    return _app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Redirect resume DB to tmp."""
    test_db = tmp_path / "test_resumes.db"
    monkeypatch.setattr("src.ml.resume_store.DB_PATH", test_db)
    return test_db


SAMPLE_RESUME = """
Summary
Backend engineer with 5+ years building scalable systems.

Experience
Stripe | Senior Backend Engineer | Jan 2022 - Present
- Built real-time data pipeline processing $2.5B in transactions
- Reduced API latency by 40% serving 10M+ requests/day

Skills
Python, Java, PostgreSQL, Redis, AWS, Docker
"""


class TestResumeUpload:
    """Test resume upload endpoint."""

    def test_upload_success(self, client):
        resp = client.post("/analysis/resumes/upload", json={
            "name": "My Resume",
            "raw_text": SAMPLE_RESUME,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "My Resume"
        assert "id" in data
        assert len(data["skill_inventory"]) > 0

    def test_upload_empty_text(self, client):
        resp = client.post("/analysis/resumes/upload", json={
            "name": "Empty",
            "raw_text": "  ",
        })
        assert resp.status_code == 400

    def test_upload_parses_skills(self, client):
        resp = client.post("/analysis/resumes/upload", json={
            "name": "Skill Resume",
            "raw_text": SAMPLE_RESUME,
        })
        data = resp.json()
        assert "python" in data["skill_inventory"]

    def test_upload_as_default(self, client):
        resp = client.post("/analysis/resumes/upload", json={
            "name": "Default",
            "raw_text": SAMPLE_RESUME,
            "is_default": True,
        })
        data = resp.json()
        assert data["is_default"] is True


class TestResumeList:
    """Test resume listing."""

    def test_list_empty(self, client):
        resp = client.get("/analysis/resumes")
        assert resp.status_code == 200
        assert resp.json()["resumes"] == []

    def test_list_after_upload(self, client):
        client.post("/analysis/resumes/upload", json={
            "name": "Resume A",
            "raw_text": SAMPLE_RESUME,
        })
        resp = client.get("/analysis/resumes")
        resumes = resp.json()["resumes"]
        assert len(resumes) == 1
        assert resumes[0]["name"] == "Resume A"


class TestResumeDetail:
    """Test resume detail endpoint."""

    def test_get_detail(self, client):
        upload = client.post("/analysis/resumes/upload", json={
            "name": "Detail Test",
            "raw_text": SAMPLE_RESUME,
        }).json()
        resp = client.get(f"/analysis/resumes/{upload['id']}")
        assert resp.status_code == 200
        assert resp.json()["raw_text"] == SAMPLE_RESUME

    def test_get_nonexistent(self, client):
        resp = client.get("/analysis/resumes/nonexistent")
        assert resp.status_code == 404


class TestResumeDelete:
    """Test resume deletion."""

    def test_delete(self, client):
        upload = client.post("/analysis/resumes/upload", json={
            "name": "Delete Me",
            "raw_text": SAMPLE_RESUME,
        }).json()
        resp = client.delete(f"/analysis/resumes/{upload['id']}")
        assert resp.status_code == 200
        # Verify gone
        assert client.get(f"/analysis/resumes/{upload['id']}").status_code == 404

    def test_delete_nonexistent(self, client):
        resp = client.delete("/analysis/resumes/nonexistent")
        assert resp.status_code == 404


class TestSetDefault:
    """Test setting default resume."""

    def test_set_default(self, client):
        a = client.post("/analysis/resumes/upload", json={
            "name": "A", "raw_text": SAMPLE_RESUME,
        }).json()
        resp = client.patch(f"/analysis/resumes/{a['id']}/default")
        assert resp.status_code == 200
        assert resp.json()["default"] == a["id"]

    def test_set_default_nonexistent(self, client):
        resp = client.patch("/analysis/resumes/nonexistent/default")
        assert resp.status_code == 404


class TestNormalizeJD:
    """Test JD normalization endpoint."""

    def test_normalize(self, client):
        resp = client.post("/analysis/normalize-jd", json={
            "title": "Senior Data Engineer",
            "description": "We need a Python developer with AWS and Spark experience. Requirements: 5+ years experience with Python, SQL, and Airflow.",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "title_norm" in data
        assert "must_have_skills" in data
        assert "confidence" in data
        assert data["confidence"] > 0

    def test_normalize_empty(self, client):
        resp = client.post("/analysis/normalize-jd", json={
            "title": "Unknown",
            "description": "",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["confidence"] <= 0.3


class TestDBHealth:
    """Test DB health endpoint."""

    def test_health_returns(self, client):
        resp = client.get("/analysis/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "resumes_db" in data
        assert "resume_count" in data
