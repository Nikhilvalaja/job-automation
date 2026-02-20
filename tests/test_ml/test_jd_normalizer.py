"""Tests for JD normalizer — boilerplate removal, skill extraction, classification."""

import pytest

from src.ml.jd_normalizer import JDNormalizer


@pytest.fixture
def normalizer():
    return JDNormalizer()


SAMPLE_JD = """
Senior Data Engineer

About the Role:
We're looking for a Senior Data Engineer to join our growing data team.
You'll build and maintain scalable data pipelines that power our analytics platform.

Responsibilities:
- Design and build data pipelines using Python and Apache Spark
- Maintain our data warehouse on Snowflake
- Implement data quality checks with Great Expectations
- Collaborate with data scientists on ML feature pipelines

Requirements:
- 5+ years of data engineering experience
- Strong Python and SQL skills
- Experience with Apache Spark or PySpark
- Knowledge of Airflow for workflow orchestration
- Experience with cloud platforms (AWS preferred)

Nice to have:
- Experience with dbt
- Knowledge of Kubernetes
- Familiarity with streaming (Kafka)

Equal Opportunity Employer: We do not discriminate based on race, color,
religion, gender, sexual orientation, national origin, age, disability,
or any other protected characteristic.

Benefits include:
- Health, dental, vision insurance
- 401k matching
- Unlimited PTO
- Remote-first culture
"""

SAMPLE_JD_NO_SECTIONS = """
We need a backend developer who knows Python, PostgreSQL, and Docker.
Experience with AWS and CI/CD is required.
Kubernetes knowledge is preferred but not mandatory.
Must have 3+ years of experience.
"""


class TestBoilerplateRemoval:
    """Test that boilerplate is removed from JDs."""

    def test_eeo_removed(self, normalizer):
        result = normalizer.normalize("Data Engineer", SAMPLE_JD)
        assert "do not discriminate" not in result.cleaned_text.lower()

    def test_benefits_removed(self, normalizer):
        result = normalizer.normalize("Data Engineer", SAMPLE_JD)
        # Benefits section should be reduced/removed
        assert "401k matching" not in result.cleaned_text

    def test_content_preserved(self, normalizer):
        result = normalizer.normalize("Data Engineer", SAMPLE_JD)
        assert "data pipelines" in result.cleaned_text.lower()
        assert "python" in result.cleaned_text.lower()


class TestSkillExtraction:
    """Test skill extraction and classification."""

    def test_must_have_skills(self, normalizer):
        result = normalizer.normalize("Senior Data Engineer", SAMPLE_JD)
        assert "python" in result.must_have_skills
        assert "sql" in result.must_have_skills
        assert "spark" in result.must_have_skills or "apache spark" in str(result.must_have_skills)

    def test_nice_to_have_skills(self, normalizer):
        result = normalizer.normalize("Senior Data Engineer", SAMPLE_JD)
        # dbt, kubernetes, kafka should be nice-to-have
        nice_set = set(result.nice_to_have_skills)
        assert "dbt" in nice_set or "kubernetes" in nice_set or "kafka" in nice_set

    def test_all_skills_superset(self, normalizer):
        result = normalizer.normalize("Senior Data Engineer", SAMPLE_JD)
        all_set = set(result.all_skills)
        must_set = set(result.must_have_skills)
        nice_set = set(result.nice_to_have_skills)
        assert must_set.issubset(all_set)
        assert nice_set.issubset(all_set)

    def test_inline_classification(self, normalizer):
        result = normalizer.normalize("Backend Developer", SAMPLE_JD_NO_SECTIONS)
        # Python, PostgreSQL, Docker should be detected
        assert "python" in result.all_skills
        assert "postgresql" in result.all_skills
        assert "docker" in result.all_skills


class TestTitleNormalization:
    """Test title normalization through JD normalizer."""

    def test_title_normalized(self, normalizer):
        result = normalizer.normalize("Sr. Data Engineer II", SAMPLE_JD)
        assert result.title_norm == "data_engineer"
        assert result.seniority_level == "senior"

    def test_location_type(self, normalizer):
        result = normalizer.normalize("Data Engineer", SAMPLE_JD)
        # "Remote-first culture" in benefits section (may be removed), check either way
        assert result.location_type in ("remote", "unknown")


class TestResponsibilities:
    """Test responsibility extraction."""

    def test_responsibilities_extracted(self, normalizer):
        result = normalizer.normalize("Data Engineer", SAMPLE_JD)
        assert len(result.responsibilities) > 0

    def test_responsibilities_content(self, normalizer):
        result = normalizer.normalize("Data Engineer", SAMPLE_JD)
        if result.responsibilities:
            all_text = " ".join(result.responsibilities).lower()
            assert "pipeline" in all_text or "data" in all_text


class TestConfidence:
    """Test confidence scoring."""

    def test_high_confidence_full_jd(self, normalizer):
        result = normalizer.normalize("Senior Data Engineer", SAMPLE_JD)
        assert result.confidence >= 0.5

    def test_low_confidence_empty(self, normalizer):
        result = normalizer.normalize("Unknown Role", "")
        assert result.confidence <= 0.3

    def test_medium_confidence_short(self, normalizer):
        result = normalizer.normalize("Backend Developer", "Need Python dev")
        assert result.confidence < 0.7

    def test_confidence_range(self, normalizer):
        result = normalizer.normalize("Data Engineer", SAMPLE_JD)
        assert 0.0 <= result.confidence <= 1.0


class TestToDict:
    """Test serialization."""

    def test_to_dict_has_all_fields(self, normalizer):
        result = normalizer.normalize("Data Engineer", SAMPLE_JD)
        d = result.to_dict()
        assert "title_norm" in d
        assert "must_have_skills" in d
        assert "nice_to_have_skills" in d
        assert "confidence" in d
        assert "cleaned_text" in d

    def test_to_dict_serializable(self, normalizer):
        import json
        result = normalizer.normalize("Data Engineer", SAMPLE_JD)
        d = result.to_dict()
        # Should be JSON-serializable
        json_str = json.dumps(d)
        assert len(json_str) > 0
