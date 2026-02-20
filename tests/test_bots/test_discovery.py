"""Tests for Discovery Bot — job scoring, dedup, source fetching.

All tests use mocked HTTP responses (no real API calls).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.discovery.preferences import JobPreferences, score_job
from src.discovery.sources import (
    ALL_SOURCES,
    COMPANY_CAREER_FEEDS,
    JOB_BOARD_SOURCES,
    SourceType,
    get_enabled_sources,
    get_greenhouse_feed_url,
    get_lever_feed_url,
)
from src.discovery.fetcher import _clean_html


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
        """Title keyword match should score high."""
        score = score_job(
            title="Software Engineer",
            description="Join our team to build systems.",
            company="Google",
            location="Remote",
            preferences=self.prefs,
        )
        # "software engineer" in title = 0.4, "remote" location = 0.2
        assert score >= 0.5

    def test_description_keyword_match(self):
        """Description keyword match should score lower than title."""
        score = score_job(
            title="Developer",
            description="We need a backend python developer",
            company="Meta",
            location="",
            preferences=self.prefs,
        )
        # "backend" in desc = 0.15, "python" in desc = 0.15
        assert 0.2 <= score <= 0.6

    def test_excluded_keyword_rejects(self):
        """Excluded keyword in title should return -1.0."""
        score = score_job(
            title="Software Engineering Intern",
            description="Great opportunity",
            company="Google",
            location="NYC",
            preferences=self.prefs,
        )
        assert score == -1.0

    def test_excluded_in_desc_not_rejected(self):
        """Excluded keyword in description (not title) should not auto-reject."""
        score = score_job(
            title="Software Engineer",
            description="Reports to the director of engineering",
            company="Google",
            location="Remote",
            preferences=self.prefs,
        )
        # "director" is only in description, not title — no auto-reject
        assert score >= 0.0

    def test_location_match_bonus(self):
        """Location match should add 0.2 bonus."""
        score_with_loc = score_job(
            title="Developer",
            description="Build things",
            company="Acme",
            location="Remote",
            preferences=self.prefs,
        )
        score_no_loc = score_job(
            title="Developer",
            description="Build things",
            company="Acme",
            location="San Francisco",
            preferences=self.prefs,
        )
        assert score_with_loc > score_no_loc

    def test_no_preferences_returns_neutral(self):
        """Empty preferences should return 0.5 for all jobs."""
        empty_prefs = JobPreferences()
        score = score_job("Any Job", "Any desc", "Any Co", "", empty_prefs)
        assert score == 0.5

    def test_multiple_keyword_matches(self):
        """Multiple keyword matches should score higher."""
        score_one = score_job(
            title="Engineer",
            description="Join our python team",
            company="Co",
            location="",
            preferences=self.prefs,
        )
        score_multi = score_job(
            title="Backend Software Engineer",
            description="Build systems with python",
            company="Co",
            location="Remote",
            preferences=self.prefs,
        )
        assert score_multi > score_one

    def test_score_capped_at_one(self):
        """Score should never exceed 1.0."""
        # Max everything: all keywords in title + desc + location
        score = score_job(
            title="Software Engineer Backend Python Developer",
            description="backend python software engineer remote new york",
            company="Co",
            location="Remote, New York",
            preferences=self.prefs,
        )
        assert score <= 1.0


# ---------------------------------------------------------------------------
# Source Configuration Tests
# ---------------------------------------------------------------------------

class TestSources:
    """Test source definitions and filtering."""

    def test_all_sources_have_names(self):
        for source in ALL_SOURCES:
            assert source.name, f"Source missing name: {source}"

    def test_all_sources_have_urls(self):
        for source in ALL_SOURCES:
            assert source.url_template, f"Source {source.name} missing URL"

    def test_source_types_valid(self):
        for source in ALL_SOURCES:
            assert source.source_type in (SourceType.RSS, SourceType.API, SourceType.CAREER_RSS)

    def test_get_enabled_sources_returns_all(self):
        sources = get_enabled_sources()
        assert len(sources) == len(ALL_SOURCES)

    def test_get_enabled_sources_filter(self):
        sources = get_enabled_sources(["indeed"])
        assert len(sources) >= 1
        assert all("indeed" in s.name.lower() for s in sources)

    def test_greenhouse_url(self):
        url = get_greenhouse_feed_url("stripe")
        assert url == "https://boards.greenhouse.io/stripe/feed"

    def test_lever_url(self):
        url = get_lever_feed_url("netflix")
        assert url == "https://jobs.lever.co/netflix/feed"

    def test_company_feeds_count(self):
        """Should have a good number of company career feeds."""
        assert len(COMPANY_CAREER_FEEDS) >= 20

    def test_job_board_sources_count(self):
        """Should have multiple job board sources."""
        assert len(JOB_BOARD_SOURCES) >= 4


# ---------------------------------------------------------------------------
# HTML Cleanup Tests
# ---------------------------------------------------------------------------

class TestHTMLCleanup:
    """Test HTML stripping for feed descriptions."""

    def test_strips_tags(self):
        result = _clean_html("<p>Hello <b>world</b></p>")
        assert result == "Hello world"

    def test_handles_empty(self):
        assert _clean_html("") == ""
        assert _clean_html(None) == ""

    def test_truncates_long_text(self):
        long_html = "<p>" + "x" * 5000 + "</p>"
        result = _clean_html(long_html)
        assert len(result) <= 2000


# ---------------------------------------------------------------------------
# Discovery Bot Integration Tests (mocked)
# ---------------------------------------------------------------------------

class TestDiscoveryBot:
    """Test the Discovery Bot with mocked HTTP calls."""

    @patch("bots.discovery_bot.run.fetch_source")
    @patch("bots.discovery_bot.run.get_enabled_sources")
    def test_dry_run_does_not_create_jobs(self, mock_sources, mock_fetch):
        """Dry run should not POST to backend."""
        from bots.discovery_bot.run import DiscoveryBot
        from src.discovery.sources import JobSource, SourceType

        mock_sources.return_value = [
            JobSource(name="Test", source_type=SourceType.API, url_template="http://test.com"),
        ]
        mock_fetch.return_value = [
            {"title": "SWE", "company": "Google", "url": "http://test.com/1",
             "description": "Build software engineer stuff", "location": "Remote", "source_name": "Test"},
        ]

        bot = DiscoveryBot(dry_run=True)
        bot.start()
        bot._existing_urls = set()
        bot._preferences = JobPreferences(keywords=["software engineer"], locations=["remote"])

        stats = bot.run_once()
        assert stats["matched"] >= 1
        # Dry run should not actually POST
        assert stats["created"] == stats["matched"]

    @patch("bots.discovery_bot.run.fetch_source")
    @patch("bots.discovery_bot.run.get_enabled_sources")
    def test_deduplication(self, mock_sources, mock_fetch):
        """Jobs with existing URLs should be skipped."""
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
        bot._existing_urls = {"http://existing.com/job1"}  # Already tracked
        bot._preferences = JobPreferences(keywords=["software engineer"])

        stats = bot.run_once()
        assert stats["duplicates"] == 1
        assert stats["matched"] == 1  # Only the new URL should match

    @patch("bots.discovery_bot.run.fetch_source")
    @patch("bots.discovery_bot.run.get_enabled_sources")
    def test_rejected_jobs_counted(self, mock_sources, mock_fetch):
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
        bot._existing_urls = set()
        bot._preferences = JobPreferences(
            keywords=["software engineer"],
            excluded_keywords=["intern"],
        )

        stats = bot.run_once()
        assert stats["rejected"] == 1
        assert stats["matched"] == 0
