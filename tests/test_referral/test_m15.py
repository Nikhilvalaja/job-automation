"""M15 tests — referral scorer v2 (role alignment, signal boost, fatigue, window timing)."""

from __future__ import annotations

import pytest
from pathlib import Path
from datetime import datetime, timedelta


@pytest.fixture
def crm_db(tmp_path):
    return tmp_path / "test_crm.db"


# ---------------------------------------------------------------------------
# Closeness (existing behaviour)
# ---------------------------------------------------------------------------

class TestCloseness:
    def _contact(self, **kwargs):
        base = {"id": "c1", "name": "Alice", "email": "alice@co.com",
                "company": "Co", "role": "", "tags": [], "notes": "",
                "status": "active", "last_contacted_at": None}
        return {**base, **kwargs}

    def test_spoke_before_is_1(self):
        from src.referral.scorer import score_contact_for_company
        c = self._contact(company="Stripe")
        rs = score_contact_for_company(c, "Stripe", touchpoints=[{"id": "t1"}], use_signals=False)
        assert rs.closeness_score == 1.0
        assert rs.tier == "direct"

    def test_works_there_no_touchpoints(self):
        from src.referral.scorer import score_contact_for_company
        c = self._contact(company="Stripe")
        rs = score_contact_for_company(c, "Stripe", touchpoints=[], use_signals=False)
        assert rs.closeness_score == 0.85

    def test_former_employee_notes(self):
        from src.referral.scorer import score_contact_for_company
        c = self._contact(company="Google", notes="formerly at Anthropic for 2 years")
        rs = score_contact_for_company(c, "Anthropic", touchpoints=[], use_signals=False)
        assert rs.tier == "former"
        assert rs.closeness_score >= 0.70

    def test_industry_overlap_tech(self):
        from src.referral.scorer import score_contact_for_company
        c = self._contact(company="TechCo SaaS", tags=["cloud"])
        rs = score_contact_for_company(c, "Stripe", touchpoints=[], use_signals=False)
        assert rs.tier == "industry"

    def test_no_connection_is_zero(self):
        from src.referral.scorer import score_contact_for_company
        c = self._contact(company="Local Bakery", notes="bakes bread")
        rs = score_contact_for_company(c, "Stripe", touchpoints=[], use_signals=False)
        assert rs.closeness_score == 0.0


# ---------------------------------------------------------------------------
# Role alignment
# ---------------------------------------------------------------------------

class TestRoleAlignment:
    def test_same_function_is_1(self):
        from src.referral.scorer import compute_role_alignment
        assert compute_role_alignment("Backend Engineer", "Backend Developer") == 1.0

    def test_devops_to_engineering_is_075(self):
        from src.referral.scorer import compute_role_alignment
        assert compute_role_alignment("DevOps Engineer", "Software Engineer") == 0.75

    def test_data_to_engineering_is_070(self):
        from src.referral.scorer import compute_role_alignment
        assert compute_role_alignment("Data Scientist", "Software Engineer") == 0.70

    def test_leadership_is_080(self):
        from src.referral.scorer import compute_role_alignment
        assert compute_role_alignment("VP Engineering", "Backend Engineer") == 0.80

    def test_sales_to_engineering_is_default(self):
        from src.referral.scorer import compute_role_alignment
        score = compute_role_alignment("Account Executive", "Backend Engineer")
        assert score == 0.40

    def test_unknown_role_partial_credit(self):
        from src.referral.scorer import compute_role_alignment
        score = compute_role_alignment("", "Backend Engineer")
        assert 0.50 <= score <= 0.70

    def test_role_alignment_multiplied_into_final(self):
        from src.referral.scorer import score_contact_for_company
        # Engineer at company → should score higher for engineering role
        c_eng = {"id": "c1", "name": "A", "email": "a@stripe.com",
                 "company": "Stripe", "role": "Backend Engineer", "tags": [],
                 "notes": "", "status": "active", "last_contacted_at": None}
        c_sales = {**c_eng, "id": "c2", "email": "b@stripe.com",
                   "role": "Account Executive"}
        rs_eng  = score_contact_for_company(c_eng,   "Stripe", "Backend Engineer", [], use_signals=False)
        rs_sales = score_contact_for_company(c_sales, "Stripe", "Backend Engineer", [], use_signals=False)
        assert rs_eng.final_score > rs_sales.final_score


# ---------------------------------------------------------------------------
# Signal boost
# ---------------------------------------------------------------------------

class TestSignalBoost:
    def test_signal_multiplier_no_db_returns_1(self):
        from src.referral.scorer import compute_signal_multiplier
        # Should not crash if signals DB is empty/unavailable
        mult, ctx = compute_signal_multiplier("RandomCompanyXYZ123")
        assert mult == 1.0

    def test_signal_boost_integrated_into_final(self, tmp_path):
        from src.signals.database import save_signal, init_signals_db
        from src.referral.scorer import score_contact_for_company
        sig_db = tmp_path / "signals.db"
        init_signals_db(sig_db)

        # Patch SIGNALS_DB_PATH so scorer picks up this test DB
        import src.signals.database as sdb
        original = sdb.SIGNALS_DB_PATH
        sdb.SIGNALS_DB_PATH = sig_db
        try:
            # High funding signal → hiring_score > 0.65
            for _ in range(3):
                save_signal("Figma", "funding", confidence=0.9, db_path=sig_db)
            contact = {"id": "cx", "name": "X", "email": "x@figma.com",
                       "company": "Figma", "role": "Engineer", "tags": [],
                       "notes": "", "status": "active", "last_contacted_at": None}
            rs = score_contact_for_company(contact, "Figma", "Backend Engineer",
                                           [{"id": "t1"}], use_signals=True)
            # Signal multiplier should be >= 1.15
            assert rs.signal_multiplier >= 1.15
            assert rs.final_score > rs.closeness_score * rs.role_alignment_score
        finally:
            sdb.SIGNALS_DB_PATH = original


# ---------------------------------------------------------------------------
# Referral fatigue
# ---------------------------------------------------------------------------

class TestReferralFatigue:
    def test_recent_message_blocks(self):
        from src.referral.scorer import check_referral_fatigue
        recent = (datetime.utcnow() - timedelta(days=3)).isoformat()
        tps = [{"id": "t1", "created_at": recent, "direction": "outbound"}]
        blocked, reason = check_referral_fatigue(tps, "")
        assert blocked is True
        assert "3d ago" in reason or "cooldown" in reason

    def test_two_unanswered_blocks(self):
        from src.referral.scorer import check_referral_fatigue
        # 2 outbound in last 30 days, no inbound
        old = (datetime.utcnow() - timedelta(days=20)).isoformat()
        tps = [
            {"id": "t1", "created_at": old, "direction": "outbound"},
            {"id": "t2", "created_at": old, "direction": "outbound"},
        ]
        blocked, reason = check_referral_fatigue(tps, "")
        assert blocked is True
        assert "unanswered" in reason

    def test_inbound_reply_unblocks(self):
        from src.referral.scorer import check_referral_fatigue
        old = (datetime.utcnow() - timedelta(days=20)).isoformat()
        tps = [
            {"id": "t1", "created_at": old, "direction": "outbound"},
            {"id": "t2", "created_at": old, "direction": "outbound"},
            {"id": "t3", "created_at": old, "direction": "inbound"},  # they replied
        ]
        blocked, _ = check_referral_fatigue(tps, "")
        assert blocked is False

    def test_no_touchpoints_is_allowed(self):
        from src.referral.scorer import check_referral_fatigue
        blocked, _ = check_referral_fatigue([], "")
        assert blocked is False

    def test_fatigue_blocked_excluded_from_finder(self, crm_db):
        from src.crm.database import upsert_contact, log_touchpoint
        from src.referral.finder import find_referral_paths
        upsert_contact("fatigued@stripe.com", name="Tired", company="Stripe", db_path=crm_db)
        # Log 2 recent outbound touchpoints
        c = upsert_contact("fatigued@stripe.com", db_path=crm_db)
        for i in range(2):
            log_touchpoint(
                contact_id=c["id"],
                type="email",
                direction="outbound",
                summary=f"sent {i}",
                db_path=crm_db,
            )
        paths = find_referral_paths("Stripe", top_n=5, min_score=0.0,
                                    use_signals=False, crm_db_path=crm_db)
        names = [p.contact_name for p in paths]
        assert "Tired" not in names


# ---------------------------------------------------------------------------
# Suggested ask context
# ---------------------------------------------------------------------------

class TestSuggestedAsk:
    def test_ask_includes_job_title(self):
        from src.referral.scorer import score_contact_for_company
        c = {"id": "c1", "name": "Alice", "email": "a@stripe.com",
             "company": "Stripe", "role": "Backend Engineer", "tags": [],
             "notes": "", "status": "active", "last_contacted_at": None}
        rs = score_contact_for_company(c, "Stripe", "ML Engineer", [{"id": "t1"}], use_signals=False)
        assert "ML Engineer" in rs.suggested_ask

    def test_ask_includes_company(self):
        from src.referral.scorer import score_contact_for_company
        c = {"id": "c2", "name": "Bob", "email": "b@anthropic.com",
             "company": "Anthropic", "role": "", "tags": [],
             "notes": "", "status": "active", "last_contacted_at": None}
        rs = score_contact_for_company(c, "Anthropic", "", [], use_signals=False)
        assert "Anthropic" in rs.suggested_ask

    def test_former_ask_mentions_worked_there(self):
        from src.referral.scorer import score_contact_for_company
        c = {"id": "c3", "name": "Carol", "email": "c@google.com",
             "company": "Google", "role": "Engineer", "tags": [],
             "notes": "formerly at Figma", "status": "active", "last_contacted_at": None}
        rs = score_contact_for_company(c, "Figma", "Designer", [], use_signals=False)
        assert rs.tier == "former"
        assert "worked" in rs.suggested_ask.lower() or "figma" in rs.suggested_ask.lower()


# ---------------------------------------------------------------------------
# Finder integration
# ---------------------------------------------------------------------------

class TestFinder:
    def test_empty_crm_returns_empty(self, crm_db):
        from src.referral.finder import find_referral_paths
        assert find_referral_paths("Stripe", crm_db_path=crm_db, use_signals=False) == []

    def test_finds_direct_contact(self, crm_db):
        from src.crm.database import upsert_contact
        from src.referral.finder import find_referral_paths
        upsert_contact("alice@stripe.com", name="Alice", company="Stripe",
                       role="Engineer", db_path=crm_db)
        paths = find_referral_paths("Stripe", "Backend Engineer", top_n=5,
                                    min_score=0.0, use_signals=False, crm_db_path=crm_db)
        assert len(paths) >= 1
        assert paths[0].tier == "direct"

    def test_score_components_present(self, crm_db):
        from src.crm.database import upsert_contact
        from src.referral.finder import find_referral_paths
        upsert_contact("y@stripe.com", name="Y", company="Stripe",
                       role="Backend Engineer", db_path=crm_db)
        paths = find_referral_paths("Stripe", "Backend Engineer", use_signals=False, crm_db_path=crm_db)
        p = paths[0]
        assert hasattr(p, "closeness_score")
        assert hasattr(p, "role_alignment_score")
        assert hasattr(p, "signal_multiplier")
        assert hasattr(p, "hiring_window_multiplier")
        assert hasattr(p, "final_score")

    def test_enrich_jobs(self, crm_db):
        from src.crm.database import upsert_contact
        from src.referral.finder import enrich_jobs_with_referrals
        upsert_contact("w@figma.com", name="Wendy", company="Figma",
                       role="Designer", db_path=crm_db)
        jobs = [{"company": "Figma", "role": "UX Designer", "id": "j1"}]
        enriched = enrich_jobs_with_referrals(jobs, use_signals=False, crm_db_path=crm_db)
        assert enriched[0]["best_referral"] is not None
