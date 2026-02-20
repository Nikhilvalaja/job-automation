"""Tests for scoring engine — weighted formula, component scores."""

import pytest
from unittest.mock import MagicMock, patch

import numpy as np

from src.ml.bullet_analyzer import AnalyzedBullet
from src.ml.embeddings import cosine_similarity
from src.ml.jd_normalizer import NormalizedJD
from src.ml.resume_parser import ExperienceEntry, ParsedResume
from src.ml.scorer import ResumeScorer, W_MUST_HAVE, W_TITLE, W_BULLET_SIM, W_DOMAIN, W_TOOLS


@pytest.fixture
def scorer():
    """Scorer with mocked embedding service (no OpenAI needed)."""
    mock_embeddings = MagicMock()
    mock_embeddings.embed_text.return_value = np.random.randn(1536).astype(np.float32)
    mock_embeddings.embed_batch.return_value = [
        np.random.randn(1536).astype(np.float32) for _ in range(10)
    ]
    return ResumeScorer(embedding_service=mock_embeddings)


@pytest.fixture
def sample_jd():
    return NormalizedJD(
        title_raw="Senior Data Engineer",
        title_norm="data_engineer",
        seniority_level="senior",
        location_type="remote",
        must_have_skills=["python", "spark", "airflow", "sql", "aws"],
        nice_to_have_skills=["dbt", "kubernetes"],
        all_skills=["python", "spark", "airflow", "sql", "aws", "dbt", "kubernetes"],
        cleaned_text="Senior Data Engineer role building data pipelines with Python, Spark, and Airflow on AWS.",
        confidence=0.85,
        skill_categories={"language": ["python", "sql"], "data_engineering": ["spark", "airflow"], "cloud": ["aws"]},
    )


@pytest.fixture
def sample_resume():
    return ParsedResume(
        raw_text="...",
        summary_lines=["5+ years backend engineer building scalable data systems"],
        experience=[
            ExperienceEntry(
                company="Stripe",
                role="Senior Backend Engineer",
                date_range="Jan 2022 - Present",
                bullets=[
                    AnalyzedBullet(
                        bullet_id="stripe_0",
                        text="Built real-time data pipeline processing $2.5B in transactions",
                        word_count=10,
                        tools=["data pipeline"],
                        metrics=["$2.5B"],
                    ),
                    AnalyzedBullet(
                        bullet_id="stripe_1",
                        text="Reduced API latency by 40% serving 10M+ requests/day",
                        word_count=9,
                        tools=["api", "redis"],
                        metrics=["40%", "10M+"],
                    ),
                ],
            )
        ],
        skills_tokens=["python", "aws", "postgresql", "redis", "docker", "spark"],
        skill_categories={"language": ["python"], "cloud": ["aws"], "database": ["postgresql", "redis"], "devops": ["docker"], "data_engineering": ["spark"]},
        skill_inventory_master_list=["python", "aws", "postgresql", "redis", "docker", "spark", "sql", "java"],
        education=["B.S. Computer Science"],
        total_bullets=2,
        total_metrics=3,
    )


class TestWeights:
    """Test that weights sum to 1.0."""

    def test_weights_sum_to_one(self):
        total = W_MUST_HAVE + W_TITLE + W_BULLET_SIM + W_DOMAIN + W_TOOLS
        assert abs(total - 1.0) < 0.001


class TestScoring:
    """Test the scoring engine."""

    def test_score_range(self, scorer, sample_jd, sample_resume):
        result = scorer.score(sample_jd, sample_resume)
        assert 0.0 <= result.match_score <= 1.0

    def test_must_have_coverage(self, scorer, sample_jd, sample_resume):
        result = scorer.score(sample_jd, sample_resume)
        # Resume has python, spark, sql, aws (4/5 must-haves) but missing airflow
        assert result.must_have_coverage > 0.5
        assert "airflow" in result.missing_must_haves

    def test_matched_skills(self, scorer, sample_jd, sample_resume):
        result = scorer.score(sample_jd, sample_resume)
        assert "python" in result.matched_skills
        assert "aws" in result.matched_skills

    def test_title_alignment(self, scorer, sample_jd, sample_resume):
        result = scorer.score(sample_jd, sample_resume)
        # "Senior Data Engineer" vs "Senior Backend Engineer" — related
        assert result.title_alignment > 0.0

    def test_tools_overlap(self, scorer, sample_jd, sample_resume):
        result = scorer.score(sample_jd, sample_resume)
        assert result.tools_overlap > 0.0
        assert result.skill_overlap_detail["matched_count"] > 0

    def test_domain_alignment(self, scorer, sample_jd, sample_resume):
        result = scorer.score(sample_jd, sample_resume)
        # Both have language, cloud, data_engineering categories
        assert result.domain_alignment > 0.0

    def test_top_bullets(self, scorer, sample_jd, sample_resume):
        result = scorer.score(sample_jd, sample_resume)
        assert len(result.top_bullets) > 0
        for bullet in result.top_bullets:
            assert "bullet_id" in bullet
            assert "similarity" in bullet

    def test_recommended_emphasis(self, scorer, sample_jd, sample_resume):
        result = scorer.score(sample_jd, sample_resume)
        assert result.recommended_emphasis in (
            "strong_match", "good_match", "skill_gap",
            "reword_bullets", "moderate_match", "weak_match",
        )


class TestPerfectMatch:
    """Test with a perfect match scenario."""

    def test_perfect_skills(self, scorer):
        jd = NormalizedJD(
            title_raw="Python Developer",
            title_norm="backend",
            seniority_level="mid",
            must_have_skills=["python", "aws"],
            all_skills=["python", "aws"],
            cleaned_text="Python developer with AWS experience",
            confidence=0.8,
        )
        resume = ParsedResume(
            raw_text="...",
            experience=[
                ExperienceEntry(
                    company="Acme",
                    role="Backend Developer",
                    bullets=[
                        AnalyzedBullet(text="Built Python services on AWS", word_count=6),
                    ],
                )
            ],
            skills_tokens=["python", "aws"],
            skill_inventory_master_list=["python", "aws"],
            skill_categories={"language": ["python"], "cloud": ["aws"]},
        )
        result = scorer.score(jd, resume)
        assert result.must_have_coverage == 1.0
        assert result.tools_overlap == 1.0


class TestEmptyInputs:
    """Test with missing data."""

    def test_empty_jd_skills(self, scorer):
        jd = NormalizedJD(title_raw="Engineer", title_norm="other", confidence=0.2)
        resume = ParsedResume(skills_tokens=["python"])
        result = scorer.score(jd, resume)
        assert 0.0 <= result.match_score <= 1.0

    def test_empty_resume(self, scorer):
        jd = NormalizedJD(
            title_raw="Engineer",
            title_norm="backend",
            must_have_skills=["python"],
            all_skills=["python"],
            cleaned_text="Need python",
            confidence=0.5,
        )
        resume = ParsedResume()
        result = scorer.score(jd, resume)
        assert result.must_have_coverage == 0.0


class TestToDict:
    """Test serialization."""

    def test_to_dict(self, scorer, sample_jd, sample_resume):
        result = scorer.score(sample_jd, sample_resume)
        d = result.to_dict()
        assert "match_score" in d
        assert "must_have_coverage" in d
        assert "missing_must_haves" in d
        assert isinstance(d["match_score"], float)


class TestCosineSimilarity:
    """Test cosine similarity function."""

    def test_identical_vectors(self):
        a = np.array([1.0, 0.0, 0.0])
        assert abs(cosine_similarity(a, a) - 1.0) < 0.001

    def test_orthogonal_vectors(self):
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 1.0, 0.0])
        assert abs(cosine_similarity(a, b)) < 0.001

    def test_zero_vector(self):
        a = np.array([1.0, 0.0, 0.0])
        b = np.zeros(3)
        assert cosine_similarity(a, b) == 0.0

    def test_opposite_vectors(self):
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([-1.0, 0.0, 0.0])
        assert cosine_similarity(a, b) < 0.0
