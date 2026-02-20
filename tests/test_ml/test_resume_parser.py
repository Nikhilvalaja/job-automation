"""Tests for resume parser — section detection, bullet analysis."""

import pytest

from src.ml.resume_parser import ResumeParser


@pytest.fixture
def parser():
    return ResumeParser()


SAMPLE_RESUME = """
Summary
Results-driven backend engineer with 5+ years building scalable systems.
Passionate about data pipelines and distributed computing.

Experience

Stripe | Senior Backend Engineer | Jan 2022 - Present
- Reduced API latency by 40% serving 10M+ requests/day using Redis caching
- Built real-time data pipeline processing $2.5B in transactions monthly
- Led migration from monolith to microservices architecture for payments team
- Mentored 3 junior engineers on distributed systems design

Meta | Backend Engineer | Jun 2019 - Dec 2021
- Designed and implemented content recommendation API serving 500M users
- Optimized PostgreSQL queries reducing p99 latency from 800ms to 200ms
- Built automated CI/CD pipeline using GitHub Actions, reducing deploy time by 60%

Skills
Python, Java, PostgreSQL, Redis, AWS, Docker, Kubernetes, Spark, Airflow,
React, Git, CI/CD, Microservices, REST API

Education
B.S. Computer Science, Stanford University, 2019
"""

SAMPLE_RESUME_MINIMAL = """
Software Developer

Built web applications using Python and Django.
Managed PostgreSQL databases.
Deployed to AWS using Docker.
"""


class TestSectionDetection:
    """Test section header detection and splitting."""

    def test_detects_experience_section(self, parser):
        result = parser.parse(SAMPLE_RESUME)
        assert len(result.experience) > 0

    def test_detects_summary(self, parser):
        result = parser.parse(SAMPLE_RESUME)
        assert len(result.summary_lines) > 0

    def test_detects_education(self, parser):
        result = parser.parse(SAMPLE_RESUME)
        assert len(result.education) > 0

    def test_detects_skills(self, parser):
        result = parser.parse(SAMPLE_RESUME)
        assert len(result.skills_tokens) > 0


class TestExperienceParsing:
    """Test experience entry parsing."""

    def test_multiple_entries(self, parser):
        result = parser.parse(SAMPLE_RESUME)
        assert len(result.experience) >= 2

    def test_company_extracted(self, parser):
        result = parser.parse(SAMPLE_RESUME)
        companies = [e.company for e in result.experience]
        assert any("Stripe" in c for c in companies) or any("stripe" in c.lower() for c in companies)

    def test_bullets_extracted(self, parser):
        result = parser.parse(SAMPLE_RESUME)
        total = sum(len(e.bullets) for e in result.experience)
        assert total >= 4  # at least 4 bullets across all entries

    def test_bullet_has_metrics(self, parser):
        result = parser.parse(SAMPLE_RESUME)
        all_bullets = [b for e in result.experience for b in e.bullets]
        has_metrics = any(b.metrics for b in all_bullets)
        assert has_metrics, "Expected at least one bullet with quantified metrics"

    def test_bullet_word_count(self, parser):
        result = parser.parse(SAMPLE_RESUME)
        all_bullets = [b for e in result.experience for b in e.bullets]
        for bullet in all_bullets:
            assert bullet.word_count > 0


class TestSkillInventory:
    """Test skill inventory master list."""

    def test_skills_extracted_from_all_sections(self, parser):
        result = parser.parse(SAMPLE_RESUME)
        skills = result.skill_inventory_master_list
        assert "python" in skills
        assert "postgresql" in skills
        assert "aws" in skills

    def test_skill_categories(self, parser):
        result = parser.parse(SAMPLE_RESUME)
        assert len(result.skill_categories) > 0
        # Should have at least language and cloud categories
        assert "language" in result.skill_categories or "cloud" in result.skill_categories

    def test_skills_deduplicated(self, parser):
        result = parser.parse(SAMPLE_RESUME)
        assert len(result.skills_tokens) == len(set(result.skills_tokens))


class TestMinimalResume:
    """Test with minimal resume format."""

    def test_handles_no_sections(self, parser):
        result = parser.parse(SAMPLE_RESUME_MINIMAL)
        # Should still extract something
        assert len(result.skills_tokens) > 0

    def test_skills_from_minimal(self, parser):
        result = parser.parse(SAMPLE_RESUME_MINIMAL)
        assert "python" in result.skills_tokens
        assert "django" in result.skills_tokens


class TestEdgeCases:
    """Test edge cases."""

    def test_empty_resume(self, parser):
        result = parser.parse("")
        assert result.total_bullets == 0
        assert len(result.skills_tokens) == 0

    def test_whitespace_only(self, parser):
        result = parser.parse("   \n\n   ")
        assert result.total_bullets == 0

    def test_to_dict(self, parser):
        result = parser.parse(SAMPLE_RESUME)
        d = result.to_dict()
        assert "experience" in d
        assert "skill_inventory_master_list" in d
        assert isinstance(d["experience"], list)

    def test_total_metrics_count(self, parser):
        result = parser.parse(SAMPLE_RESUME)
        assert result.total_metrics >= 1
