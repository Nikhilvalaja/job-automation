"""Tests for Discovery Bot — scoring, dedup, DB, parser, sources.

All tests use mocked HTTP responses and in-memory/temp DB.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from src.discovery.preferences import JobPreferences, score_job
from src.discovery.sources import (
    ALL_SOURCES,
    COMPANY_CAREER_FEEDS,
    GREENHOUSE_FEEDS,
    JOB_BOARD_SOURCES,
    LEVER_FEEDS,
    ASHBY_FEEDS,
    SourceType,
    get_enabled_sources,
    get_greenhouse_feed_url,
    get_lever_feed_url,
    get_ashby_feed_url,
)
from src.discovery.fetcher import _clean_html
from src.discovery.parser import JobParser, _detect_category, _detect_level, _detect_years_min
from src.discovery.database import _compute_fingerprint


# ---------------------------------------------------------------------------
# Job Scoring Tests
# ---------------------------------------------------------------------------

class TestJobScoring:
    """Test the preference-based job scoring engine."""

    def setup_method(self):
        self.prefs = JobPreferences(
            keywords=["software engineer", "backend", "python"],
            excluded_keywords=["intern", "director"],
            locations=["remote", "new york"],
            min_match_score=0.3,
        )

    def test_title_keyword_match(self):
        score = score_job("Software Engineer", "Join our team.", "Google", "Remote", self.prefs)
        assert score >= 0.5

    def test_description_keyword_match(self):
        score = score_job("Developer", "We need a backend python developer", "Meta", "", self.prefs)
        assert 0.2 <= score <= 0.6

    def test_excluded_keyword_rejects(self):
        score = score_job("Software Engineering Intern", "Great", "Google", "NYC", self.prefs)
        assert score == -1.0

    def test_excluded_in_desc_not_rejected(self):
        score = score_job("Software Engineer", "Reports to the director", "Google", "Remote", self.prefs)
        assert score >= 0.0

    def test_location_match_bonus(self):
        s1 = score_job("Developer", "Build things", "Acme", "Remote", self.prefs)
        s2 = score_job("Developer", "Build things", "Acme", "San Francisco", self.prefs)
        assert s1 > s2

    def test_no_preferences_returns_neutral(self):
        score = score_job("Any Job", "Any desc", "Any Co", "", JobPreferences())
        assert score == 0.5

    def test_multiple_keyword_matches(self):
        s1 = score_job("Engineer", "Join our python team", "Co", "", self.prefs)
        s2 = score_job("Backend Software Engineer", "Build with python", "Co", "Remote", self.prefs)
        assert s2 > s1

    def test_score_capped_at_one(self):
        score = score_job(
            "Software Engineer Backend Python Developer",
            "backend python software engineer remote new york",
            "Co", "Remote, New York", self.prefs,
        )
        assert score <= 1.0


# ---------------------------------------------------------------------------
# Source Configuration Tests
# ---------------------------------------------------------------------------

class TestSources:
    """Test source definitions and filtering."""

    def test_all_sources_have_names(self):
        for source in ALL_SOURCES:
            assert source.name

    def test_all_sources_have_urls(self):
        for source in ALL_SOURCES:
            assert source.url_template

    def test_source_types_valid(self):
        for source in ALL_SOURCES:
            assert source.source_type in (SourceType.RSS, SourceType.API, SourceType.CAREER_RSS)

    def test_total_sources_over_250(self):
        """Should have 250+ total sources."""
        assert len(ALL_SOURCES) >= 250

    def test_greenhouse_feeds_over_150(self):
        assert len(GREENHOUSE_FEEDS) >= 150

    def test_lever_feeds_over_60(self):
        assert len(LEVER_FEEDS) >= 60

    def test_ashby_feeds_over_25(self):
        assert len(ASHBY_FEEDS) >= 25

    def test_job_boards_over_10(self):
        assert len(JOB_BOARD_SOURCES) >= 10

    def test_get_enabled_sources_filter(self):
        sources = get_enabled_sources(["indeed"])
        assert len(sources) >= 1
        assert all("indeed" in s.name.lower() for s in sources)

    def test_greenhouse_url(self):
        assert get_greenhouse_feed_url("stripe") == "https://boards.greenhouse.io/stripe/feed"

    def test_lever_url(self):
        assert get_lever_feed_url("netflix") == "https://jobs.lever.co/netflix/feed"

    def test_ashby_url(self):
        assert get_ashby_feed_url("linear") == "https://jobs.ashbyhq.com/linear/feed"

    def test_no_duplicate_names(self):
        """Each source should have a unique name."""
        names = [s.name for s in ALL_SOURCES]
        assert len(names) == len(set(names)), f"Duplicate source names found"


# ---------------------------------------------------------------------------
# HTML Cleanup Tests
# ---------------------------------------------------------------------------

class TestHTMLCleanup:
    def test_strips_tags(self):
        assert _clean_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_handles_empty(self):
        assert _clean_html("") == ""
        assert _clean_html(None) == ""

    def test_truncates_long_text(self):
        assert len(_clean_html("<p>" + "x" * 5000 + "</p>")) <= 2000


# ---------------------------------------------------------------------------
# Keyword Parser Tests
# ---------------------------------------------------------------------------

class TestKeywordParser:
    """Test the keyword-based job parser (no GPT needed)."""

    def test_detect_backend_category(self):
        assert _detect_category("backend engineer", "api development") == "backend"

    def test_detect_data_science_category(self):
        assert _detect_category("data scientist", "machine learning models") == "data_science"

    def test_detect_ml_category(self):
        assert _detect_category("ml engineer", "deep learning") == "ml_engineer"

    def test_detect_business_analyst(self):
        assert _detect_category("business analyst", "reporting") == "business_analyst"

    def test_detect_senior_level(self):
        assert _detect_level("senior software engineer", "") == "senior"

    def test_detect_entry_level(self):
        assert _detect_level("junior developer", "") == "entry"

    def test_detect_staff_level(self):
        assert _detect_level("staff engineer", "") == "staff"

    def test_detect_mid_level_default(self):
        assert _detect_level("software engineer", "") == "mid"

    def test_detect_years(self):
        assert _detect_years_min("requires 3+ years of experience") == 3

    def test_parse_full_job(self):
        parser = JobParser()
        result = parser.parse({
            "title": "Senior Backend Engineer",
            "company": "Stripe",
            "description": "5+ years experience with python, aws, postgresql. Remote role. Bachelor's degree required.",
            "location": "Remote",
        })
        assert result["category"] == "backend"
        assert result["experience_level"] == "senior"
        assert result["experience_years_min"] == 5
        assert result["remote_type"] == "remote"
        assert "python" in result["skills"]
        assert result["education"] == "bachelors"

    def test_parser_validates_fields(self):
        """Parser should clean up invalid values."""
        parser = JobParser()
        result = parser._validate_fields({
            "category": "INVALID",
            "experience_level": "BOGUS",
            "job_type": "weird",
        })
        assert result["category"] == "other"
        assert result["experience_level"] == "mid"
        assert result["job_type"] == "full_time"


class TestFingerprint:
    """Test the dedup fingerprint system."""

    def test_same_job_same_fingerprint(self):
        fp1 = _compute_fingerprint("Software Engineer", "Google", "Remote")
        fp2 = _compute_fingerprint("Software Engineer", "Google", "Remote")
        assert fp1 == fp2

    def test_case_insensitive(self):
        fp1 = _compute_fingerprint("Software Engineer", "Google", "Remote")
        fp2 = _compute_fingerprint("software engineer", "google", "remote")
        assert fp1 == fp2

    def test_different_jobs_different_fingerprint(self):
        fp1 = _compute_fingerprint("Software Engineer", "Google", "Remote")
        fp2 = _compute_fingerprint("Data Scientist", "Meta", "NYC")
        assert fp1 != fp2


# ---------------------------------------------------------------------------
# Database Tests
# ---------------------------------------------------------------------------

class TestDiscoveryDatabase:
    """Test SQLite database operations."""

    def test_init_db(self, tmp_path):
        """Database should initialize without errors."""
        with patch("src.discovery.database.DB_PATH", tmp_path / "test.db"):
            from src.discovery.database import init_db, get_db
            init_db()
            conn = get_db()
            # Check table exists
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='discovered_jobs'"
            ).fetchall()
            conn.close()
            assert len(rows) == 1

    def test_insert_and_search(self, tmp_path):
        """Should insert a job and find it via search."""
        with patch("src.discovery.database.DB_PATH", tmp_path / "test.db"):
            from src.discovery.database import init_db, insert_job, search_jobs
            init_db()

            job_id = insert_job({
                "title": "Backend Engineer",
                "company": "Stripe",
                "url": "https://stripe.com/jobs/1",
                "description": "Build payment systems",
                "location": "Remote",
                "source_name": "Greenhouse",
                "score": 0.8,
            })
            assert job_id is not None

            jobs, total = search_jobs(company="Stripe")
            assert total == 1
            assert jobs[0]["company"] == "Stripe"

    def test_duplicate_url_rejected(self, tmp_path):
        """Duplicate URLs should return None."""
        with patch("src.discovery.database.DB_PATH", tmp_path / "test.db"):
            from src.discovery.database import init_db, insert_job
            init_db()

            id1 = insert_job({"title": "Job1", "url": "https://test.com/1", "company": ""})
            id2 = insert_job({"title": "Job2", "url": "https://test.com/1", "company": ""})
            assert id1 is not None
            assert id2 is None  # Duplicate

    def test_get_stats(self, tmp_path):
        """Stats should reflect inserted jobs."""
        with patch("src.discovery.database.DB_PATH", tmp_path / "test.db"):
            from src.discovery.database import init_db, insert_job, get_stats
            init_db()
            insert_job({"title": "SWE", "url": "https://a.com/1", "company": "A"})
            insert_job({"title": "MLE", "url": "https://b.com/2", "company": "B"})

            stats = get_stats()
            assert stats["total"] == 2

    def test_get_job_by_id(self, tmp_path):
        """Should retrieve a job by ID."""
        with patch("src.discovery.database.DB_PATH", tmp_path / "test.db"):
            from src.discovery.database import init_db, insert_job, get_job_by_id
            init_db()
            job_id = insert_job({"title": "SWE", "url": "https://a.com/1", "company": "Google"})
            job = get_job_by_id(job_id)
            assert job is not None
            assert job["title"] == "SWE"
            assert job["company"] == "Google"
            assert get_job_by_id("nonexistent") is None

    def test_mark_applied(self, tmp_path):
        """Should mark job as applied with timestamp."""
        with patch("src.discovery.database.DB_PATH", tmp_path / "test.db"):
            from src.discovery.database import init_db, insert_job, mark_applied, get_job_by_id
            init_db()
            job_id = insert_job({"title": "SWE", "url": "https://a.com/1", "company": "A"})
            mark_applied(job_id)
            job = get_job_by_id(job_id)
            assert job["status"] == "applied"
            assert job["applied_at"] != ""

    def test_sort_by_newest(self, tmp_path):
        """Should sort by newest first."""
        with patch("src.discovery.database.DB_PATH", tmp_path / "test.db"):
            from src.discovery.database import init_db, insert_job, search_jobs
            init_db()
            insert_job({"title": "Job1", "url": "https://a.com/1", "company": "A"})
            insert_job({"title": "Job2", "url": "https://b.com/2", "company": "B"})
            jobs, total = search_jobs(sort_by="newest")
            assert total == 2
            # Newest first means Job2 should come first
            assert jobs[0]["title"] == "Job2"

    def test_fingerprint_computed(self, tmp_path):
        """Inserted jobs should have a fingerprint."""
        with patch("src.discovery.database.DB_PATH", tmp_path / "test.db"):
            from src.discovery.database import init_db, insert_job, get_job_by_id
            init_db()
            job_id = insert_job({"title": "SWE", "url": "https://a.com/1", "company": "Google", "location": "Remote"})
            job = get_job_by_id(job_id)
            assert job["fingerprint"] != ""

    def test_source_stats_tracking(self, tmp_path):
        """Should track per-source statistics."""
        with patch("src.discovery.database.DB_PATH", tmp_path / "test.db"):
            from src.discovery.database import init_db, update_source_stats, get_source_stats
            init_db()
            update_source_stats("TestSource", "api", "http://test.com", 10)
            stats = get_source_stats()
            assert len(stats) == 1
            assert stats[0]["source_name"] == "TestSource"
            assert stats[0]["total_jobs_found"] == 10


# ---------------------------------------------------------------------------
# Discovery Bot Integration Tests (mocked)
# ---------------------------------------------------------------------------

class TestDiscoveryBot:
    """Test the Discovery Bot with mocked sources and DB."""

    @patch("bots.discovery_bot.run.insert_job", return_value="abc123")
    @patch("bots.discovery_bot.run.update_parsed_fields")
    @patch("bots.discovery_bot.run.get_all_urls", return_value=set())
    @patch("bots.discovery_bot.run.fetch_source")
    @patch("bots.discovery_bot.run.get_enabled_sources")
    def test_discovery_stores_to_db(self, mock_sources, mock_fetch, mock_urls, mock_update, mock_insert):
        """Discovery should store matched jobs in SQLite."""
        from bots.discovery_bot.run import DiscoveryBot
        from src.discovery.sources import JobSource, SourceType

        mock_sources.return_value = [
            JobSource(name="Test", source_type=SourceType.API, url_template="http://test.com"),
        ]
        mock_fetch.return_value = [
            {"title": "Software Engineer", "company": "Google", "url": "http://test.com/1",
             "description": "Build software engineer systems", "location": "Remote", "source_name": "Test"},
        ]

        bot = DiscoveryBot(dry_run=False)
        bot.start()
        bot._preferences = JobPreferences(keywords=["software engineer"], locations=["remote"])

        stats = bot.run_once()
        assert stats["matched"] >= 1
        assert stats["stored"] >= 1
        mock_insert.assert_called()

    @patch("bots.discovery_bot.run.get_all_urls", return_value={"http://existing.com/job1"})
    @patch("bots.discovery_bot.run.fetch_source")
    @patch("bots.discovery_bot.run.get_enabled_sources")
    def test_deduplication_via_db(self, mock_sources, mock_fetch, mock_urls):
        """Jobs with URLs already in DB should be skipped."""
        from bots.discovery_bot.run import DiscoveryBot
        from src.discovery.sources import JobSource, SourceType

        mock_sources.return_value = [
            JobSource(name="Test", source_type=SourceType.API, url_template="http://test.com"),
        ]
        mock_fetch.return_value = [
            {"title": "Software Engineer", "company": "Google", "url": "http://existing.com/job1",
             "description": "build systems", "location": "", "source_name": "Test"},
            {"title": "Software Engineer", "company": "Meta", "url": "http://new.com/job2",
             "description": "build systems", "location": "", "source_name": "Test"},
        ]

        bot = DiscoveryBot(dry_run=True)
        bot.start()
        bot._preferences = JobPreferences(keywords=["software engineer"])

        stats = bot.run_once()
        assert stats["duplicates"] == 1
        assert stats["matched"] == 1

    @patch("bots.discovery_bot.run.get_all_urls", return_value=set())
    @patch("bots.discovery_bot.run.fetch_source")
    @patch("bots.discovery_bot.run.get_enabled_sources")
    def test_rejected_jobs_counted(self, mock_sources, mock_fetch, mock_urls):
        """Jobs with excluded keywords should be rejected."""
        from bots.discovery_bot.run import DiscoveryBot
        from src.discovery.sources import JobSource, SourceType

        mock_sources.return_value = [
            JobSource(name="Test", source_type=SourceType.API, url_template="http://test.com"),
        ]
        mock_fetch.return_value = [
            {"title": "Software Engineering Intern", "company": "Google",
             "url": "http://test.com/intern", "description": "", "location": "", "source_name": "Test"},
        ]

        bot = DiscoveryBot(dry_run=True)
        bot.start()
        bot._preferences = JobPreferences(
            keywords=["software engineer"],
            excluded_keywords=["intern"],
        )

        stats = bot.run_once()
        assert stats["rejected"] == 1
        assert stats["matched"] == 0
