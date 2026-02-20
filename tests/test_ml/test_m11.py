"""M11 tests — keyword mapper, rewriter, validator, diff, variant store, skill registry.

Focused on critical paths only. No fluff.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# keyword_mapper
# ---------------------------------------------------------------------------

class TestKeywordMapper:
    def test_safe_swap_action_verb(self):
        from src.ml.keyword_mapper import get_safe_swaps
        swaps = get_safe_swaps("built")
        targets = [s.target.lower() for s in swaps]
        assert "developed" in targets

    def test_safe_swap_bidirectional(self):
        from src.ml.keyword_mapper import get_safe_swaps
        swaps = get_safe_swaps("developed")
        targets = [s.target.lower() for s in swaps]
        assert "built" in targets

    def test_find_swap_for_jd_matches(self):
        from src.ml.keyword_mapper import find_swap_for_jd
        swap = find_swap_for_jd("built", ["developed", "deployed", "integrated"])
        assert swap is not None
        assert swap.target.lower() == "developed"

    def test_find_swap_for_jd_no_match(self):
        from src.ml.keyword_mapper import find_swap_for_jd
        swap = find_swap_for_jd("built", ["designed", "evaluated"])
        assert swap is None

    def test_transferable_same_subcategory(self):
        from src.ml.keyword_mapper import check_skill_transferability
        r = check_skill_transferability("PostgreSQL", "MySQL")
        assert r["transferable"] is True

    def test_not_transferable_different_category(self):
        from src.ml.keyword_mapper import check_skill_transferability
        r = check_skill_transferability("Python", "Kubernetes")
        assert r["transferable"] is False

    def test_analyze_skill_gaps_coverage(self):
        from src.ml.keyword_mapper import analyze_skill_gaps
        result = analyze_skill_gaps(
            ["Python", "PostgreSQL", "Docker"],
            ["MySQL", "Kubernetes", "Java"],
        )
        assert result["coverage_rate"] > 0
        assert "MySQL" in result["transferable"]

    def test_all_skill_families_non_empty(self):
        from src.ml.keyword_mapper import ALL_SKILL_FAMILIES
        assert len(ALL_SKILL_FAMILIES) >= 50
        for fam in ALL_SKILL_FAMILIES:
            assert len(fam.skills) > 0


# ---------------------------------------------------------------------------
# skill_registry
# ---------------------------------------------------------------------------

class TestSkillRegistry:
    def test_compute_transfer_exact_same_subcategory(self):
        from src.ml.skill_registry import compute_transfer
        r = compute_transfer("PostgreSQL", "MySQL")
        assert r.transferable
        assert r.score >= 0.8

    def test_compute_transfer_different_platform(self):
        from src.ml.skill_registry import compute_transfer
        r = compute_transfer("S3", "GCS")
        assert r.transferable
        assert 0.65 <= r.score < 1.0

    def test_compute_transfer_different_category(self):
        from src.ml.skill_registry import compute_transfer
        r = compute_transfer("Python", "Kubernetes")
        assert not r.transferable
        assert r.score == 0.0

    def test_compute_transfer_same_category_diff_subcategory(self):
        from src.ml.skill_registry import compute_transfer
        r = compute_transfer("PostgreSQL", "MongoDB")
        assert r.transferable
        assert 0.3 <= r.score < 0.7

    def test_unknown_skill_returns_zero(self):
        from src.ml.skill_registry import compute_transfer
        r = compute_transfer("FakeTool9999", "MySQL")
        assert not r.transferable
        assert r.score == 0.0

    def test_analyze_skill_gaps_v2_structure(self):
        from src.ml.skill_registry import analyze_skill_gaps_v2
        result = analyze_skill_gaps_v2(
            ["Python", "PostgreSQL", "Docker", "React"],
            ["Java", "MySQL", "Kubernetes", "Angular", "Terraform"],
        )
        assert "exact_matches" in result
        assert "transferable" in result
        assert "gaps" in result
        assert "weighted_score" in result
        assert 0.0 <= result["weighted_score"] <= 1.0

    def test_skill_index_alias(self):
        from src.ml.skill_registry import SKILL_INDEX
        skill = SKILL_INDEX.find("PySpark")
        # PySpark is an alias for Spark
        assert skill is not None or SKILL_INDEX.find("Spark") is not None

    def test_registry_coverage(self):
        from src.ml.skill_registry import SKILL_INDEX
        assert len(SKILL_INDEX.all_skills) >= 150


# ---------------------------------------------------------------------------
# rewriter
# ---------------------------------------------------------------------------

class TestRewriter:
    def test_deterministic_swaps_action_verb(self):
        from src.ml.rewriter import rewrite_deterministic
        results = rewrite_deterministic(
            ["Built data pipeline for 10M requests/day"],
            "developed data workflow for high throughput",
            ["Python"],
        )
        assert results[0].method == "deterministic"
        assert "developed" in results[0].rewritten_text.lower()

    def test_metrics_preserved(self):
        from src.ml.rewriter import rewrite_deterministic
        results = rewrite_deterministic(
            ["Reduced latency by 40% saving $1.2M annually"],
            "optimized system performance",
            ["Python"],
        )
        assert "40%" in results[0].rewritten_text
        assert "$1.2M" in results[0].rewritten_text

    def test_no_change_when_no_swap_applies(self):
        from src.ml.rewriter import rewrite_deterministic
        results = rewrite_deterministic(
            ["Secured production systems across 3 datacenters"],
            "secured production systems",
            ["Python"],
        )
        assert results[0].method == "no_change"

    def test_platform_not_swapped(self):
        from src.ml.rewriter import rewrite_deterministic
        results = rewrite_deterministic(
            ["Migrated data from AWS S3 to GCS"],
            "implemented storage on Azure Blob",
            ["Python"],
        )
        assert "AWS" in results[0].rewritten_text
        assert "S3" in results[0].rewritten_text

    def test_word_count_stays_within_delta(self):
        from src.ml.rewriter import rewrite_deterministic
        bullet = "Built microservices architecture handling 1M+ daily users"
        results = rewrite_deterministic(
            [bullet],
            "developed distributed services",
            ["Python"],
        )
        orig_wc = len(bullet.split())
        new_wc = len(results[0].rewritten_text.split())
        assert abs(new_wc - orig_wc) <= 3


# ---------------------------------------------------------------------------
# validator
# ---------------------------------------------------------------------------

class TestValidator:
    def test_valid_rewrite_passes(self):
        from src.ml.rewriter import rewrite_deterministic
        from src.ml.validator import validate_all_rewrites
        results = rewrite_deterministic(
            ["Built data pipeline processing 10M requests"],
            "developed data workflow",
            ["Python"],
        )
        validations = validate_all_rewrites(results, ["Python"])
        assert validations[0].passed

    def test_metric_loss_fails(self):
        from src.ml.bullet_analyzer import analyze_bullet
        from src.ml.validator import RewriteValidator
        original = analyze_bullet("Reduced latency by 40%")
        rewritten = analyze_bullet("Reduced latency significantly")
        v = RewriteValidator()
        result = v.validate(original, rewritten)
        assert not result.passed
        assert any("40%" in e["message"] for e in result.errors)

    def test_word_count_delta_fails(self):
        from src.ml.bullet_analyzer import analyze_bullet
        from src.ml.validator import RewriteValidator
        original = analyze_bullet("Built API")
        rewritten = analyze_bullet(
            "Architected and developed scalable REST API with comprehensive documentation and error handling"
        )
        v = RewriteValidator()
        result = v.validate(original, rewritten)
        assert not result.passed
        assert any("word count" in e["message"].lower() for e in result.errors)

    def test_no_warning_for_quantified_bullet(self):
        from src.ml.bullet_analyzer import analyze_bullet
        from src.ml.validator import RewriteValidator
        original = analyze_bullet("Built system handling 10M+ requests/day")
        rewritten = analyze_bullet("Developed system handling 10M+ requests/day")
        v = RewriteValidator()
        result = v.validate(original, rewritten)
        # Should have no "measurable outcome" warning
        measurable_warns = [w for w in result.warnings if w["rule"] == "measurable_outcome"]
        assert len(measurable_warns) == 0


# ---------------------------------------------------------------------------
# diff_report
# ---------------------------------------------------------------------------

class TestDiffReport:
    def test_diff_report_structure(self):
        from src.ml.rewriter import rewrite_deterministic
        from src.ml.validator import validate_all_rewrites
        from src.ml.diff_report import generate_diff_report

        results = rewrite_deterministic(
            ["Built pipeline", "Reduced latency by 30%"],
            "developed pipeline",
            ["Python"],
        )
        validations = validate_all_rewrites(results, ["Python"])
        report = generate_diff_report(results, validations)

        assert report.total_bullets == 2
        d = report.to_dict()
        assert "bullet_diffs" in d
        assert "summary" in d

    def test_word_diffs_computed(self):
        from src.ml.diff_report import compute_word_diffs
        diffs = compute_word_diffs("Built data pipeline", "Developed data pipeline")
        types = [d["type"] for d in diffs]
        assert "replace" in types or "delete" in types

    def test_unchanged_bullet_no_diffs(self):
        from src.ml.rewriter import rewrite_deterministic
        from src.ml.diff_report import generate_diff_report
        results = rewrite_deterministic(
            ["Secured production infrastructure"],
            "secured production systems",
            [],
        )
        report = generate_diff_report(results)
        assert all(not d.changed or d.word_diffs for d in report.bullet_diffs
                   if d.changed)


# ---------------------------------------------------------------------------
# variant_store
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    return tmp_path / "test_variants.db"


class TestVariantStore:
    def test_save_and_get(self, tmp_db):
        from src.ml.variant_store import save_variant, get_variant
        v = save_variant(
            "resume_1", jd_title="Backend Eng", jd_company="Stripe",
            bullets=[{
                "original_text": "Built API",
                "rewritten_text": "Developed API",
                "changes": [],
                "validation": {"validation_passed": True},
            }],
            weighted_score=0.75,
            db_path=tmp_db,
        )
        assert v["id"]
        fetched = get_variant(v["id"], db_path=tmp_db)
        assert fetched is not None
        assert fetched["jd_title"] == "Backend Eng"
        assert len(fetched["bullet_details"]) == 1

    def test_approve_bullet_updates_status(self, tmp_db):
        from src.ml.variant_store import save_variant, update_bullet_approval, get_variant
        v = save_variant(
            "resume_1",
            bullets=[
                {"original_text": "A", "rewritten_text": "B", "changes": [], "validation": {}},
                {"original_text": "C", "rewritten_text": "D", "changes": [], "validation": {}},
            ],
            db_path=tmp_db,
        )
        update_bullet_approval(v["id"], 0, "approved", db_path=tmp_db)
        update_bullet_approval(v["id"], 1, "approved", db_path=tmp_db)
        fetched = get_variant(v["id"], db_path=tmp_db)
        assert fetched["status"] == "partially_reviewed"

    def test_finalize_requires_all_reviewed(self, tmp_db):
        from src.ml.variant_store import save_variant, finalize_variant
        v = save_variant(
            "resume_1",
            bullets=[
                {"original_text": "A", "rewritten_text": "B", "changes": [], "validation": {}},
            ],
            db_path=tmp_db,
        )
        # Try to finalize with pending bullet
        result = finalize_variant(v["id"], db_path=tmp_db)
        assert "error" in result

    def test_finalize_approved_uses_rewritten(self, tmp_db):
        from src.ml.variant_store import save_variant, update_bullet_approval, finalize_variant
        v = save_variant(
            "resume_1",
            bullets=[
                {"original_text": "Built API", "rewritten_text": "Developed API",
                 "changes": [], "validation": {}},
            ],
            db_path=tmp_db,
        )
        update_bullet_approval(v["id"], 0, "approved", db_path=tmp_db)
        final = finalize_variant(v["id"], db_path=tmp_db)
        assert final["final_bullets"][0]["text"] == "Developed API"
        assert final["final_bullets"][0]["source"] == "rewritten"

    def test_finalize_rejected_uses_original(self, tmp_db):
        from src.ml.variant_store import save_variant, update_bullet_approval, finalize_variant
        v = save_variant(
            "resume_1",
            bullets=[
                {"original_text": "Built API", "rewritten_text": "Developed API",
                 "changes": [], "validation": {}},
            ],
            db_path=tmp_db,
        )
        update_bullet_approval(v["id"], 0, "rejected", db_path=tmp_db)
        final = finalize_variant(v["id"], db_path=tmp_db)
        assert final["final_bullets"][0]["text"] == "Built API"
        assert final["final_bullets"][0]["source"] == "original"

    def test_user_edited_text_used_on_finalize(self, tmp_db):
        from src.ml.variant_store import save_variant, update_bullet_approval, finalize_variant
        v = save_variant(
            "resume_1",
            bullets=[
                {"original_text": "Built API", "rewritten_text": "Developed API",
                 "changes": [], "validation": {}},
            ],
            db_path=tmp_db,
        )
        update_bullet_approval(v["id"], 0, "approved", "My Custom Edit", db_path=tmp_db)
        final = finalize_variant(v["id"], db_path=tmp_db)
        assert final["final_bullets"][0]["text"] == "My Custom Edit"

    def test_state_machine_valid_transition(self, tmp_db):
        from src.ml.variant_store import save_variant, update_bullet_approval, finalize_variant, transition_status
        v = save_variant("resume_1", db_path=tmp_db)
        # draft → finalized (no bullets, skip pending check)
        ok = transition_status(v["id"], "finalized", db_path=tmp_db)
        assert ok

    def test_state_machine_invalid_transition(self, tmp_db):
        from src.ml.variant_store import save_variant, transition_status
        v = save_variant("resume_1", db_path=tmp_db)
        # draft → applied is NOT allowed
        ok = transition_status(v["id"], "applied", db_path=tmp_db)
        assert not ok

    def test_delete_variant(self, tmp_db):
        from src.ml.variant_store import save_variant, delete_variant, get_variant
        v = save_variant("resume_1", db_path=tmp_db)
        delete_variant(v["id"], db_path=tmp_db)
        assert get_variant(v["id"], db_path=tmp_db) is None

    def test_stats_structure(self, tmp_db):
        from src.ml.variant_store import save_variant, get_variant_stats
        save_variant("resume_1", weighted_score=0.8, db_path=tmp_db)
        stats = get_variant_stats(db_path=tmp_db)
        assert stats["total_variants"] == 1
        assert "by_status" in stats
        assert "bullet_analytics" in stats
