"""M13 tests — signals database, classifier, scorer, normalizer."""

from __future__ import annotations

import pytest
from pathlib import Path


@pytest.fixture
def tmp_db(tmp_path):
    return tmp_path / "test_signals.db"


# ---------------------------------------------------------------------------
# normalizer
# ---------------------------------------------------------------------------

class TestNormalizer:
    def test_strip_legal_suffix_inc(self):
        from src.signals.normalizer import normalize_company
        assert normalize_company("Stripe Inc.") == "Stripe"

    def test_strip_legal_suffix_llc(self):
        from src.signals.normalizer import normalize_company
        assert normalize_company("DataDog LLC") == "DataDog"

    def test_alias_meta(self):
        from src.signals.normalizer import normalize_company
        assert normalize_company("Meta Platforms, Inc.") == "Meta"
        assert normalize_company("Facebook") == "Meta"

    def test_alias_google(self):
        from src.signals.normalizer import normalize_company
        assert normalize_company("Alphabet Inc.") == "Google"

    def test_companies_are_same(self):
        from src.signals.normalizer import companies_are_same
        assert companies_are_same("Stripe Inc.", "Stripe")
        assert companies_are_same("Meta Platforms, Inc.", "Facebook")

    def test_companies_different(self):
        from src.signals.normalizer import companies_are_same
        assert not companies_are_same("Stripe", "Square")

    def test_empty_returns_empty(self):
        from src.signals.normalizer import normalize_company
        assert normalize_company("") == ""


# ---------------------------------------------------------------------------
# database
# ---------------------------------------------------------------------------

class TestSignalsDB:
    def test_save_signal_creates_company_score(self, tmp_db):
        from src.signals.database import save_signal, get_company_score
        save_signal("Stripe", "funding", signal_text="Stripe raises $100M", confidence=0.9, db_path=tmp_db)
        score = get_company_score("Stripe", db_path=tmp_db)
        assert score is not None
        assert score["hiring_score"] > 0.5
        assert score["signal_count"] == 1

    def test_layoff_signal_reduces_score(self, tmp_db):
        from src.signals.database import save_signal, get_company_score
        save_signal("Lyft", "layoff", confidence=0.9, db_path=tmp_db)
        score = get_company_score("Lyft", db_path=tmp_db)
        assert score["hiring_score"] < 0.5

    def test_funding_sets_last_funding_at(self, tmp_db):
        from src.signals.database import save_signal, get_company_score
        save_signal("Anthropic", "funding", confidence=0.9, db_path=tmp_db)
        score = get_company_score("Anthropic", db_path=tmp_db)
        assert score.get("last_funding_at") is not None

    def test_canonical_name_stored(self, tmp_db):
        from src.signals.database import save_signal, get_company_score
        save_signal("Meta Platforms, Inc.", "funding", confidence=0.8, db_path=tmp_db)
        score = get_company_score("Meta Platforms, Inc.", db_path=tmp_db)
        assert score["canonical_name"] == "Meta"

    def test_multiple_signals_accumulate(self, tmp_db):
        from src.signals.database import save_signal, get_company_score
        save_signal("DataDog", "funding", confidence=0.9, db_path=tmp_db)
        save_signal("DataDog", "expansion", confidence=0.8, db_path=tmp_db)
        score = get_company_score("DataDog", db_path=tmp_db)
        assert score["signal_count"] == 2

    def test_stats_structure(self, tmp_db):
        from src.signals.database import save_signal, get_signals_stats
        save_signal("Meta", "funding", confidence=0.8, db_path=tmp_db)
        stats = get_signals_stats(db_path=tmp_db)
        assert "total_signals" in stats
        assert "by_type" in stats
        assert "companies_tracked" in stats


# ---------------------------------------------------------------------------
# classifier
# ---------------------------------------------------------------------------

class TestClassifier:
    def test_classify_funding(self):
        from src.signals.classifier import classify_text
        r = classify_text("Stripe raises $200M in Series G funding round")
        assert r.signal_type == "funding"
        assert r.confidence >= 0.5

    def test_classify_layoff(self):
        from src.signals.classifier import classify_text
        r = classify_text("Company announces layoff of 500 employees in workforce reduction")
        assert r.signal_type == "layoff"

    def test_classify_acquisition(self):
        from src.signals.classifier import classify_text
        r = classify_text("Microsoft acquires Activision in deal worth $69B")
        assert r.signal_type == "acquisition"

    def test_classify_noise(self):
        from src.signals.classifier import classify_text
        r = classify_text("The weather today is sunny with light clouds")
        assert r.signal_type == "noise"

    def test_amount_extracted(self):
        from src.signals.classifier import classify_text
        r = classify_text("OpenAI raises $500M from Microsoft")
        assert r.amount == "$500M"

    def test_company_normalized(self):
        from src.signals.classifier import classify_text
        r = classify_text("Stripe Inc. raises $200M in new funding round")
        assert r.company == "Stripe"

    def test_sector_tags_detected(self):
        from src.signals.classifier import classify_text
        r = classify_text("Epic Systems expands healthcare EHR platform for hospital networks")
        assert "healthcare" in r.sector_tags

    def test_is_actionable(self):
        from src.signals.classifier import classify_text, is_actionable
        r = classify_text("Anthropic raises $750M Series C")
        assert is_actionable(r)


# ---------------------------------------------------------------------------
# scorer
# ---------------------------------------------------------------------------

class TestScorer:
    def test_hiring_window_warm(self):
        from src.signals.scorer import compute_hiring_window
        from datetime import datetime, timedelta
        recent = (datetime.utcnow() - timedelta(days=10)).isoformat()
        assert compute_hiring_window(recent) == "warm"

    def test_hiring_window_peak(self):
        from src.signals.scorer import compute_hiring_window
        from datetime import datetime, timedelta
        mid = (datetime.utcnow() - timedelta(days=50)).isoformat()
        assert compute_hiring_window(mid) == "peak"

    def test_hiring_window_cooling(self):
        from src.signals.scorer import compute_hiring_window
        from datetime import datetime, timedelta
        old = (datetime.utcnow() - timedelta(days=120)).isoformat()
        assert compute_hiring_window(old) == "cooling"

    def test_hiring_window_unknown(self):
        from src.signals.scorer import compute_hiring_window
        assert compute_hiring_window(None) == "unknown"

    def test_sector_boost_backend(self):
        from src.signals.scorer import compute_sector_boost
        texts = ["Stripe expanding cloud infrastructure and kubernetes platform"]
        boost = compute_sector_boost(texts, target_role="backend")
        assert boost > 0.0

    def test_sector_boost_no_match(self):
        from src.signals.scorer import compute_sector_boost
        texts = ["Retail store opening in downtown Chicago"]
        boost = compute_sector_boost(texts, target_role="backend")
        assert boost == 0.0

    def test_signal_confidence_multiple(self, tmp_db):
        from src.signals.database import save_signal
        from src.signals.scorer import compute_signal_confidence
        for _ in range(3):
            save_signal("Stripe", "funding", confidence=0.8, db_path=tmp_db)
        conf = compute_signal_confidence("Stripe", db_path=tmp_db)
        assert conf >= 0.90

    def test_priority_score_formula(self):
        from src.signals.scorer import compute_priority_score
        score = compute_priority_score(
            match_score=0.85,
            signal_score=0.80,
            sector_boost=0.20,
            hiring_window="peak",
            has_layoff=False,
        )
        assert 0.70 < score <= 1.0

    def test_priority_score_layoff_penalty(self):
        from src.signals.scorer import compute_priority_score
        with_layoff = compute_priority_score(0.80, 0.80, 0.10, "peak", has_layoff=True)
        without_layoff = compute_priority_score(0.80, 0.80, 0.10, "peak", has_layoff=False)
        assert with_layoff < without_layoff

    def test_refresh_company_score_stores_window(self, tmp_db):
        from src.signals.database import save_signal
        from src.signals.scorer import refresh_company_score
        save_signal("Figma", "funding", confidence=0.9, db_path=tmp_db)
        result = refresh_company_score("Figma", db_path=tmp_db)
        assert "hiring_window" in result
        assert result["hiring_window"] in ("warm", "peak", "cooling", "unknown")
