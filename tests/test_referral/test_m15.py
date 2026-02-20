"""M15 tests — referral scorer and finder."""

from __future__ import annotations

import pytest
from pathlib import Path


@pytest.fixture
def crm_db(tmp_path):
    return tmp_path / "test_crm.db"


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------

class TestReferralScorer:
    def test_direct_contact_at_company(self):
        from src.referral.scorer import score_contact_for_company
        contact = {
            "id": "c1", "name": "Alice", "email": "alice@stripe.com",
            "company": "Stripe", "tags": [], "notes": "", "status": "active",
            "last_contacted_at": None,
        }
        rs = score_contact_for_company(contact, "Stripe", touchpoints=[{"id": "t1"}])
        assert rs.score == 1.0
        assert rs.tier == "direct"

    def test_works_at_company_no_touchpoints(self):
        from src.referral.scorer import score_contact_for_company
        contact = {
            "id": "c2", "name": "Bob", "email": "bob@stripe.com",
            "company": "Stripe", "tags": [], "notes": "", "status": "active",
            "last_contacted_at": None,
        }
        rs = score_contact_for_company(contact, "Stripe", touchpoints=[])
        assert rs.score == 0.85
        assert rs.tier == "direct"

    def test_former_employee_tag(self):
        from src.referral.scorer import score_contact_for_company
        contact = {
            "id": "c3", "name": "Carol", "email": "carol@google.com",
            "company": "Google", "tags": ["ex-stripe", "alumni"], "notes": "",
            "status": "active", "last_contacted_at": None,
        }
        rs = score_contact_for_company(contact, "Stripe", touchpoints=[])
        assert rs.tier == "former"
        assert rs.score >= 0.70

    def test_former_employee_notes(self):
        from src.referral.scorer import score_contact_for_company
        contact = {
            "id": "c4", "name": "Dave", "email": "dave@acme.com",
            "company": "ACME", "tags": [], "notes": "formerly at Anthropic for 2 years",
            "status": "active", "last_contacted_at": None,
        }
        rs = score_contact_for_company(contact, "Anthropic", touchpoints=[])
        assert rs.tier == "former"

    def test_industry_overlap_tech(self):
        from src.referral.scorer import score_contact_for_company
        contact = {
            "id": "c5", "name": "Eve", "email": "eve@techco.com",
            "company": "TechCo SaaS", "tags": ["cloud"], "notes": "works in saas",
            "status": "active", "last_contacted_at": None,
        }
        rs = score_contact_for_company(contact, "Stripe", touchpoints=[])
        assert rs.score > 0.0
        assert rs.tier == "industry"

    def test_no_connection(self):
        from src.referral.scorer import score_contact_for_company
        contact = {
            "id": "c6", "name": "Frank", "email": "frank@bakery.com",
            "company": "Frank's Bakery", "tags": [], "notes": "local bakery owner",
            "status": "active", "last_contacted_at": None,
        }
        rs = score_contact_for_company(contact, "Stripe", touchpoints=[])
        assert rs.tier == "none"
        assert rs.score == 0.0

    def test_company_name_normalization(self):
        from src.referral.scorer import score_contact_for_company
        contact = {
            "id": "c7", "name": "Grace", "email": "grace@stripe.com",
            "company": "Stripe, Inc.", "tags": [], "notes": "",
            "status": "active", "last_contacted_at": None,
        }
        rs = score_contact_for_company(contact, "Stripe", touchpoints=[])
        assert rs.tier == "direct"

    def test_recency_bonus_recent(self):
        from src.referral.scorer import score_contact_for_company
        from datetime import datetime, timedelta
        recent = (datetime.utcnow() - timedelta(days=5)).isoformat()
        contact = {
            "id": "c8", "name": "Hank", "email": "hank@stripe.com",
            "company": "Stripe", "tags": [], "notes": "",
            "status": "active", "last_contacted_at": recent,
        }
        rs_with = score_contact_for_company(contact, "Stripe", touchpoints=[])
        contact_no_touch = {**contact, "last_contacted_at": None}
        rs_without = score_contact_for_company(contact_no_touch, "Stripe", touchpoints=[])
        assert rs_with.score >= rs_without.score

    def test_suggested_ask_present(self):
        from src.referral.scorer import score_contact_for_company
        contact = {
            "id": "c9", "name": "Iris", "email": "iris@meta.com",
            "company": "Meta", "tags": [], "notes": "",
            "status": "active", "last_contacted_at": None,
        }
        rs = score_contact_for_company(contact, "Meta", touchpoints=[])
        assert rs.suggested_ask
        assert "Meta" in rs.suggested_ask


# ---------------------------------------------------------------------------
# Finder (integration — uses real CRM DB)
# ---------------------------------------------------------------------------

class TestReferralFinder:
    def test_empty_crm_returns_empty(self, crm_db):
        from src.referral.finder import find_referral_paths
        paths = find_referral_paths("Stripe", crm_db_path=crm_db)
        assert paths == []

    def test_finds_direct_contact(self, crm_db):
        from src.crm.database import upsert_contact
        from src.referral.finder import find_referral_paths
        upsert_contact("alice@stripe.com", name="Alice", company="Stripe", db_path=crm_db)
        paths = find_referral_paths("Stripe", top_n=5, min_score=0.0, crm_db_path=crm_db)
        assert len(paths) >= 1
        assert paths[0].tier == "direct"
        assert paths[0].contact_name == "Alice"

    def test_best_path_sorted_first(self, crm_db):
        from src.crm.database import upsert_contact
        from src.referral.finder import find_referral_paths
        upsert_contact("x@unrelated.com", name="X", company="Bakery", db_path=crm_db)
        upsert_contact("y@stripe.com", name="Y", company="Stripe", db_path=crm_db)
        paths = find_referral_paths("Stripe", top_n=5, min_score=0.0, crm_db_path=crm_db)
        assert paths[0].company.lower().startswith("stripe") or paths[0].score >= paths[-1].score

    def test_get_referral_summary(self, crm_db):
        from src.crm.database import upsert_contact
        from src.referral.finder import get_referral_summary
        upsert_contact("z@anthropic.com", name="Zoe", company="Anthropic", db_path=crm_db)
        summary = get_referral_summary("Anthropic", crm_db_path=crm_db)
        assert summary["company"] == "Anthropic"
        assert summary["total_paths"] >= 1
        assert summary["best_path"] is not None

    def test_no_referral_summary(self, crm_db):
        from src.referral.finder import get_referral_summary
        summary = get_referral_summary("NoSuchCo", crm_db_path=crm_db)
        assert summary["best_path"] is None
        assert summary["total_paths"] == 0

    def test_enrich_jobs(self, crm_db):
        from src.crm.database import upsert_contact
        from src.referral.finder import enrich_jobs_with_referrals
        upsert_contact("w@figma.com", name="Wendy", company="Figma", db_path=crm_db)
        jobs = [{"company": "Figma", "role": "Frontend Engineer", "id": "j1"}]
        enriched = enrich_jobs_with_referrals(jobs, top_n=3, crm_db_path=crm_db)
        assert len(enriched) == 1
        assert enriched[0]["best_referral"] is not None
        assert enriched[0]["best_referral"]["name"] == "Wendy"
