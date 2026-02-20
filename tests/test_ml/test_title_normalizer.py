"""Tests for title normalizer — role detection and seniority."""

import pytest

from src.ml.title_normalizer import normalize_title, titles_match


class TestNormalizeTitle:
    """Test title normalization."""

    def test_basic_backend(self):
        result = normalize_title("Backend Engineer")
        assert result.canonical == "backend"
        assert result.seniority == "mid"

    def test_senior_data_engineer(self):
        result = normalize_title("Sr. Data Engineer II")
        assert result.canonical == "data_engineer"
        assert result.seniority == "senior"

    def test_junior_developer(self):
        result = normalize_title("Junior Backend Developer")
        assert result.canonical == "backend"
        assert result.seniority == "entry"

    def test_staff_ml_engineer(self):
        result = normalize_title("Staff ML Engineer")
        assert result.canonical == "ml_engineer"
        assert result.seniority == "staff"

    def test_lead_fullstack(self):
        result = normalize_title("Lead Full Stack Developer")
        assert result.canonical == "fullstack"
        assert result.seniority == "lead"

    def test_principal_engineer(self):
        result = normalize_title("Principal Software Engineer")
        assert result.canonical == "software_engineer"
        assert result.seniority == "principal"

    def test_devops_sre(self):
        result = normalize_title("Senior Site Reliability Engineer")
        assert result.canonical == "devops"
        assert result.seniority == "senior"

    def test_product_manager(self):
        result = normalize_title("Senior Product Manager")
        assert result.canonical == "product_manager"
        assert result.seniority == "senior"

    def test_mobile_developer(self):
        result = normalize_title("iOS Developer")
        assert result.canonical == "mobile"

    def test_data_scientist(self):
        result = normalize_title("Data Scientist")
        assert result.canonical == "data_scientist"

    def test_qa_engineer(self):
        result = normalize_title("QA Engineer")
        assert result.canonical == "qa"

    def test_unknown_title(self):
        result = normalize_title("Chief Happiness Officer")
        assert result.canonical == "other"

    def test_empty_title(self):
        result = normalize_title("")
        assert result.canonical == "other"
        assert result.seniority == "mid"

    def test_clean_strips_level_and_numerals(self):
        result = normalize_title("Senior Backend Engineer III")
        assert "senior" not in result.clean
        assert "iii" not in result.clean

    def test_director_level(self):
        result = normalize_title("Director of Engineering")
        assert result.seniority == "director"


class TestTitlesMatch:
    """Test title similarity computation."""

    def test_exact_match(self):
        score = titles_match("Backend Engineer", "Backend Engineer")
        assert score >= 0.9

    def test_same_role_different_level(self):
        score = titles_match("Senior Backend Engineer", "Backend Engineer")
        assert score >= 0.6  # same role, adjacent level

    def test_related_roles(self):
        score = titles_match("Backend Engineer", "Full Stack Developer")
        assert score > 0.2  # related

    def test_unrelated_roles(self):
        score = titles_match("Backend Engineer", "Product Manager")
        assert score <= 0.3

    def test_same_role_same_level(self):
        score = titles_match("Senior Data Engineer", "Sr. Data Engineer")
        assert score >= 0.8
