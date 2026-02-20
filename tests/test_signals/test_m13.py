"""M13 tests — signals database, classifier, scorer."""

from __future__ import annotations

import pytest
from pathlib import Path


@pytest.fixture
def tmp_db(tmp_path):
    return tmp_path / "test_signals.db"


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

    def test_multiple_signals_accumulate(self, tmp_db):
        from src.signals.database import save_signal, get_company_score
        save_signal("DataDog", "funding", confidence=0.9, db_path=tmp_db)
        save_signal("DataDog", "expansion", confidence=0.8, db_path=tmp_db)
        score = get_company_score("DataDog", db_path=tmp_db)
        assert score["signal_count"] == 2
        assert score["hiring_score"] > 0.5

    def test_get_signals_filter_by_type(self, tmp_db):
        from src.signals.database import save_signal, get_signals
        save_signal("Google", "funding", confidence=0.8, db_path=tmp_db)
        save_signal("Google", "layoff", confidence=0.7, db_path=tmp_db)
        layoff_sigs = get_signals(signal_type="layoff", db_path=tmp_db)
        assert all(s["signal_type"] == "layoff" for s in layoff_sigs)

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
        assert r.confidence >= 0.5

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

    def test_company_extracted(self):
        from src.signals.classifier import classify_text
        r = classify_text("Stripe raises $200M in new funding round")
        assert "stripe" in r.company.lower()

    def test_is_actionable(self):
        from src.signals.classifier import classify_text, is_actionable
        r = classify_text("Anthropic raises $750M Series C")
        assert is_actionable(r)

    def test_noise_not_actionable(self):
        from src.signals.classifier import classify_text, is_actionable
        r = classify_text("Nothing of note happened today in tech")
        assert not is_actionable(r)


# ---------------------------------------------------------------------------
# scorer
# ---------------------------------------------------------------------------

class TestScorer:
    def test_recompute_score_no_signals(self, tmp_db):
        from src.signals.scorer import recompute_company_score
        score = recompute_company_score("Unknown Corp", db_path=tmp_db)
        assert score == 0.50  # neutral default

    def test_recompute_after_funding(self, tmp_db):
        from src.signals.database import save_signal
        from src.signals.scorer import recompute_company_score
        save_signal("Figma", "funding", confidence=0.9, db_path=tmp_db)
        score = recompute_company_score("Figma", db_path=tmp_db)
        assert score > 0.50

    def test_refresh_persists(self, tmp_db):
        from src.signals.database import save_signal, get_company_score
        from src.signals.scorer import refresh_company_score
        save_signal("Airbnb", "expansion", confidence=0.8, db_path=tmp_db)
        result = refresh_company_score("Airbnb", db_path=tmp_db)
        assert result["hiring_score"] > 0.50
        assert "trend" in result

    def test_get_top_companies(self, tmp_db):
        from src.signals.database import save_signal
        from src.signals.scorer import get_top_companies, refresh_company_score
        save_signal("TopCo", "funding", confidence=0.95, db_path=tmp_db)
        save_signal("TopCo", "expansion", confidence=0.90, db_path=tmp_db)
        refresh_company_score("TopCo", db_path=tmp_db)
        top = get_top_companies(min_score=0.5, db_path=tmp_db)
        assert any(c["company"] == "TopCo" for c in top)

    def test_enrich_jobs_with_signals(self, tmp_db):
        from src.signals.database import save_signal
        from src.signals.scorer import enrich_jobs_with_signals
        save_signal("Twilio", "funding", confidence=0.8, db_path=tmp_db)
        enriched = enrich_jobs_with_signals(["Twilio", "Unknown"], db_path=tmp_db)
        assert "Twilio" in enriched
        assert "Unknown" in enriched
        assert enriched["Twilio"]["signal_count"] >= 1
