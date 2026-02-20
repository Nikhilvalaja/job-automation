"""Tests for resume store — CRUD, default management, parsing."""

import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch

from src.ml.resume_store import (
    init_resume_db,
    save_resume,
    get_resume,
    list_resumes,
    set_default_resume,
    delete_resume,
    get_default_resume,
    get_resume_count,
    DB_PATH,
)


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Redirect DB_PATH to a temporary directory for each test."""
    test_db = tmp_path / "test_resumes.db"
    monkeypatch.setattr("src.ml.resume_store.DB_PATH", test_db)
    return test_db


SAMPLE_RESUME_TEXT = """
Summary
Backend engineer with 5+ years building scalable systems.

Experience
Stripe | Senior Backend Engineer | Jan 2022 - Present
- Built real-time data pipeline processing $2.5B in transactions
- Reduced API latency by 40% serving 10M+ requests/day

Skills
Python, Java, PostgreSQL, Redis, AWS, Docker, Kubernetes

Education
B.S. Computer Science, Stanford, 2019
"""


class TestSaveResume:
    """Test resume creation."""

    def test_save_basic(self):
        record = save_resume(name="Test Resume", raw_text=SAMPLE_RESUME_TEXT)
        assert record is not None
        assert record["name"] == "Test Resume"
        assert record["raw_text"] == SAMPLE_RESUME_TEXT
        assert "id" in record

    def test_save_with_parsed_data(self):
        record = save_resume(
            name="Parsed Resume",
            raw_text=SAMPLE_RESUME_TEXT,
            parsed_json={"experience": []},
            skill_inventory=["python", "aws"],
            skill_categories={"language": ["python"], "cloud": ["aws"]},
            total_bullets=2,
            total_metrics=3,
        )
        assert record["skill_inventory"] == ["python", "aws"]
        assert record["skill_categories"]["language"] == ["python"]
        assert record["total_bullets"] == 2
        assert record["total_metrics"] == 3

    def test_save_as_default(self):
        save_resume(name="Resume A", raw_text="text a", is_default=True)
        record = save_resume(name="Resume B", raw_text="text b", is_default=True)
        # B should now be default, A should not
        resumes = list_resumes()
        for r in resumes:
            if r["name"] == "Resume B":
                assert r["is_default"] is True
            elif r["name"] == "Resume A":
                assert r["is_default"] is False


class TestGetResume:
    """Test resume retrieval."""

    def test_get_existing(self):
        saved = save_resume(name="My Resume", raw_text="text")
        fetched = get_resume(saved["id"])
        assert fetched is not None
        assert fetched["name"] == "My Resume"

    def test_get_nonexistent(self):
        assert get_resume("nonexistent") is None

    def test_get_parses_json_fields(self):
        saved = save_resume(
            name="JSON Resume",
            raw_text="text",
            skill_inventory=["python"],
            parsed_json={"key": "value"},
        )
        fetched = get_resume(saved["id"])
        assert isinstance(fetched["skill_inventory"], list)
        assert isinstance(fetched["parsed_json"], dict)
        assert fetched["is_default"] is False


class TestListResumes:
    """Test listing resumes."""

    def test_empty_list(self):
        assert list_resumes() == []

    def test_list_multiple(self):
        save_resume(name="A", raw_text="text a")
        save_resume(name="B", raw_text="text b")
        save_resume(name="C", raw_text="text c")
        resumes = list_resumes()
        assert len(resumes) == 3

    def test_default_first(self):
        save_resume(name="A", raw_text="text a")
        save_resume(name="B", raw_text="text b", is_default=True)
        resumes = list_resumes()
        assert resumes[0]["name"] == "B"
        assert resumes[0]["is_default"] is True

    def test_list_excludes_raw_text(self):
        save_resume(name="A", raw_text="very long text")
        resumes = list_resumes()
        # raw_text should not be in the list response
        assert "raw_text" not in resumes[0]


class TestSetDefault:
    """Test setting default resume."""

    def test_set_default(self):
        a = save_resume(name="A", raw_text="a", is_default=True)
        b = save_resume(name="B", raw_text="b")
        assert set_default_resume(b["id"]) is True
        default = get_default_resume()
        assert default["name"] == "B"

    def test_set_default_nonexistent(self):
        assert set_default_resume("nonexistent") is False


class TestDeleteResume:
    """Test resume deletion."""

    def test_delete_existing(self):
        saved = save_resume(name="Delete Me", raw_text="text")
        assert delete_resume(saved["id"]) is True
        assert get_resume(saved["id"]) is None

    def test_delete_nonexistent(self):
        assert delete_resume("nonexistent") is False

    def test_delete_reduces_count(self):
        a = save_resume(name="A", raw_text="a")
        save_resume(name="B", raw_text="b")
        assert get_resume_count() == 2
        delete_resume(a["id"])
        assert get_resume_count() == 1


class TestGetDefaultResume:
    """Test default resume retrieval."""

    def test_returns_default(self):
        save_resume(name="A", raw_text="a")
        save_resume(name="B", raw_text="b", is_default=True)
        default = get_default_resume()
        assert default["name"] == "B"

    def test_returns_most_recent_if_no_default(self):
        save_resume(name="Old", raw_text="old")
        save_resume(name="New", raw_text="new")
        default = get_default_resume()
        assert default["name"] == "New"

    def test_returns_none_if_empty(self):
        assert get_default_resume() is None


class TestResumeCount:
    """Test resume count."""

    def test_zero(self):
        assert get_resume_count() == 0

    def test_count_after_adds(self):
        save_resume(name="A", raw_text="a")
        save_resume(name="B", raw_text="b")
        assert get_resume_count() == 2
