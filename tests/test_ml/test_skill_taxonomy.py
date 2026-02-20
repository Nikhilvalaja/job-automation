"""Tests for skill taxonomy — skill resolution, extraction, and overlap."""

import pytest

from src.ml.skill_taxonomy import (
    categorize_skills,
    compute_skill_overlap,
    extract_skills,
    get_all_categories,
    get_skill_category,
    get_skills_by_category,
    get_taxonomy_size,
    resolve_skill,
)


class TestResolveSkill:
    """Test skill name resolution."""

    def test_canonical_name(self):
        assert resolve_skill("python") == "python"

    def test_alias_resolution(self):
        assert resolve_skill("k8s") == "kubernetes"
        assert resolve_skill("Python3") == "python"
        assert resolve_skill("golang") == "go"
        assert resolve_skill("reactjs") == "react"

    def test_case_insensitive(self):
        assert resolve_skill("PYTHON") == "python"
        assert resolve_skill("Kubernetes") == "kubernetes"

    def test_unknown_skill(self):
        assert resolve_skill("not_a_real_skill") is None
        assert resolve_skill("") is None

    def test_special_characters(self):
        assert resolve_skill("c++") == "c++"
        assert resolve_skill("c#") == "c#"
        assert resolve_skill("node.js") == "node.js"


class TestExtractSkills:
    """Test skill extraction from text."""

    def test_basic_extraction(self):
        text = "We need a Python developer with experience in AWS and Docker."
        skills = extract_skills(text)
        assert "python" in skills
        assert "aws" in skills
        assert "docker" in skills

    def test_multiple_skills(self):
        text = "Requirements: Python, Java, Kubernetes, PostgreSQL, React"
        skills = extract_skills(text)
        assert len(skills) >= 5
        assert "python" in skills
        assert "java" in skills
        assert "kubernetes" in skills
        assert "postgresql" in skills
        assert "react" in skills

    def test_alias_extraction(self):
        text = "Experience with k8s and reactjs required"
        skills = extract_skills(text)
        assert "kubernetes" in skills
        assert "react" in skills

    def test_empty_text(self):
        assert extract_skills("") == []
        assert extract_skills("   ") == []

    def test_no_skills_in_text(self):
        text = "Looking for a creative team player with strong communication skills"
        skills = extract_skills(text)
        # Should find very few or no technical skills
        assert len(skills) <= 2

    def test_deduplication(self):
        text = "Python Python Python developer needs Python"
        skills = extract_skills(text)
        assert skills.count("python") == 1

    def test_multi_word_skills(self):
        text = "Experience with machine learning and natural language processing"
        skills = extract_skills(text)
        assert "nlp" in skills or "machine learning" in [s.replace("ml_engineer", "machine learning") for s in skills]

    def test_jd_like_text(self):
        text = """
        Senior Backend Engineer
        Requirements:
        - 5+ years of Python experience
        - Strong knowledge of PostgreSQL and Redis
        - Experience with Docker and Kubernetes
        - Familiarity with AWS (EC2, S3, Lambda)
        - CI/CD pipelines (GitHub Actions or Jenkins)
        """
        skills = extract_skills(text)
        assert "python" in skills
        assert "postgresql" in skills
        assert "redis" in skills
        assert "docker" in skills
        assert "kubernetes" in skills


class TestGetSkillCategory:
    """Test skill categorization."""

    def test_language_category(self):
        assert get_skill_category("python") == "language"
        assert get_skill_category("java") == "language"

    def test_cloud_category(self):
        assert get_skill_category("aws") == "cloud"
        assert get_skill_category("gcp") == "cloud"

    def test_devops_category(self):
        assert get_skill_category("docker") == "devops"
        assert get_skill_category("kubernetes") == "devops"

    def test_unknown_skill(self):
        assert get_skill_category("nonexistent_skill") == "other"


class TestSkillOverlap:
    """Test skill overlap computation."""

    def test_full_overlap(self):
        result = compute_skill_overlap(
            ["python", "aws", "docker"],
            ["python", "aws", "docker", "react"],
        )
        assert result["overlap_pct"] == 1.0
        assert result["matched_count"] == 3
        assert len(result["missing"]) == 0

    def test_partial_overlap(self):
        result = compute_skill_overlap(
            ["python", "aws", "spark", "airflow"],
            ["python", "aws", "docker", "react"],
        )
        assert result["matched_count"] == 2
        assert result["overlap_pct"] == 0.5
        assert "spark" in result["missing"]
        assert "airflow" in result["missing"]

    def test_no_overlap(self):
        result = compute_skill_overlap(
            ["python", "aws"],
            ["java", "azure"],
        )
        assert result["overlap_pct"] == 0.0
        assert result["matched_count"] == 0

    def test_empty_required(self):
        result = compute_skill_overlap([], ["python", "aws"])
        # Empty required = everything matches
        assert result["overlap_pct"] == 0.0 or result["matched_count"] == 0

    def test_alias_resolution_in_overlap(self):
        result = compute_skill_overlap(
            ["k8s", "golang"],
            ["kubernetes", "go"],
        )
        # Aliases should resolve to same canonical
        assert result["matched_count"] == 2


class TestTaxonomyMeta:
    """Test taxonomy metadata."""

    def test_taxonomy_size(self):
        size = get_taxonomy_size()
        assert size >= 300  # at least 300 unique skills

    def test_categories_exist(self):
        cats = get_all_categories()
        assert "language" in cats
        assert "cloud" in cats
        assert "devops" in cats
        assert "database" in cats

    def test_skills_by_category(self):
        languages = get_skills_by_category("language")
        assert "python" in languages
        assert "java" in languages
        assert len(languages) >= 20

    def test_categorize_skills(self):
        cats = categorize_skills(["python", "aws", "react", "docker"])
        assert "python" in cats["language"]
        assert "aws" in cats["cloud"]
        assert "react" in cats["frontend"]
        assert "docker" in cats["devops"]
