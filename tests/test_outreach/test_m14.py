"""M14 tests — outreach database, drafter, sequences, rules."""

from __future__ import annotations

import pytest
from pathlib import Path


@pytest.fixture
def tmp_db(tmp_path):
    return tmp_path / "test_outreach.db"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

class TestOutreachDB:
    def test_start_sequence_creates_record(self, tmp_db):
        from src.outreach.database import start_sequence, get_sequence
        seq = start_sequence(
            contact_id="c1",
            contact_email="alice@stripe.com",
            contact_name="Alice",
            company="Stripe",
            db_path=tmp_db,
        )
        assert seq["id"] is not None
        assert seq["status"] == "active"
        assert seq["current_stage"] == "initial"

    def test_start_sequence_idempotent(self, tmp_db):
        from src.outreach.database import start_sequence
        seq1 = start_sequence("c2", "bob@google.com", db_path=tmp_db)
        seq2 = start_sequence("c2", "bob@google.com", db_path=tmp_db)
        assert seq1["id"] == seq2["id"]

    def test_save_and_get_draft(self, tmp_db):
        from src.outreach.database import start_sequence, save_draft, get_draft
        seq = start_sequence("c3", "carol@meta.com", company="Meta", db_path=tmp_db)
        draft = save_draft(
            sequence_id=seq["id"],
            contact_id="c3",
            contact_email="carol@meta.com",
            stage="initial",
            subject="Hi from Nikhil",
            body="Hey Carol, I'd love to connect...",
            db_path=tmp_db,
        )
        assert draft["status"] == "pending"
        fetched = get_draft(draft["id"], db_path=tmp_db)
        assert fetched["subject"] == "Hi from Nikhil"

    def test_approve_draft(self, tmp_db):
        from src.outreach.database import start_sequence, save_draft, approve_draft
        seq = start_sequence("c4", "d@openai.com", db_path=tmp_db)
        draft = save_draft(
            sequence_id=seq["id"], contact_id="c4", contact_email="d@openai.com",
            stage="initial", subject="Sub", body="Body text here",
            db_path=tmp_db,
        )
        approved = approve_draft(draft["id"], db_path=tmp_db)
        assert approved["status"] == "approved"

    def test_reject_draft(self, tmp_db):
        from src.outreach.database import start_sequence, save_draft, reject_draft, get_draft
        seq = start_sequence("c5", "e@anthropic.com", db_path=tmp_db)
        draft = save_draft(
            sequence_id=seq["id"], contact_id="c5", contact_email="e@anthropic.com",
            stage="initial", subject="S", body="B",
            db_path=tmp_db,
        )
        reject_draft(draft["id"], notes="tone off", db_path=tmp_db)
        d = get_draft(draft["id"], db_path=tmp_db)
        assert d["status"] == "rejected"

    def test_advance_sequence(self, tmp_db):
        from src.outreach.database import start_sequence, advance_sequence
        seq = start_sequence("c6", "f@figma.com", db_path=tmp_db)
        assert seq["current_stage"] == "initial"
        updated = advance_sequence(seq["id"], db_path=tmp_db)
        assert updated["current_stage"] == "follow_up_1"

    def test_mark_replied(self, tmp_db):
        from src.outreach.database import start_sequence, mark_sequence_replied, get_sequence
        seq = start_sequence("c7", "g@notion.so", db_path=tmp_db)
        mark_sequence_replied(seq["id"], db_path=tmp_db)
        updated = get_sequence(seq["id"], db_path=tmp_db)
        assert updated["status"] == "replied"
        assert updated["reply_received"] == 1

    def test_stats_structure(self, tmp_db):
        from src.outreach.database import start_sequence, get_outreach_stats
        start_sequence("c8", "h@vercel.com", company="Vercel", db_path=tmp_db)
        stats = get_outreach_stats(db_path=tmp_db)
        assert "total_sequences" in stats
        assert "active_sequences" in stats
        assert "pending_drafts" in stats
        assert "reply_rate" in stats

    def test_list_drafts_by_status(self, tmp_db):
        from src.outreach.database import start_sequence, save_draft, list_drafts
        seq = start_sequence("c9", "i@linear.app", db_path=tmp_db)
        save_draft(
            sequence_id=seq["id"], contact_id="c9", contact_email="i@linear.app",
            stage="initial", subject="Test", body="Test body",
            db_path=tmp_db,
        )
        pending = list_drafts(status="pending", db_path=tmp_db)
        assert len(pending) >= 1

    def test_variant_tracking(self, tmp_db):
        from src.outreach.database import record_variant_send, get_variant_stats
        record_variant_send("A", "initial", db_path=tmp_db)
        record_variant_send("A", "initial", db_path=tmp_db)
        record_variant_send("B", "initial", db_path=tmp_db)
        stats = get_variant_stats(db_path=tmp_db)
        labels = [v["variant_label"] for v in stats]
        assert "A" in labels
        assert "B" in labels


# ---------------------------------------------------------------------------
# Drafter
# ---------------------------------------------------------------------------

class TestDrafter:
    def test_template_initial_draft(self):
        from src.outreach.drafter import draft_with_template
        result = draft_with_template(
            stage="initial",
            contact_name="Alice",
            company="Stripe",
            sender_name="Nikhil",
        )
        assert result.subject
        assert result.body
        assert result.word_count <= 160  # allow slight margin
        assert result.drafted_by == "template"

    def test_template_follow_up_1(self):
        from src.outreach.drafter import draft_with_template
        result = draft_with_template(stage="follow_up_1", contact_name="Bob", company="Meta")
        assert "follow" in result.body.lower() or "circle" in result.body.lower() or "note" in result.body.lower()

    def test_template_follow_up_2(self):
        from src.outreach.drafter import draft_with_template
        result = draft_with_template(stage="follow_up_2", contact_name="Carol", company="Google")
        assert result.body

    def test_generate_draft_dispatches(self):
        from src.outreach.drafter import generate_draft
        result = generate_draft(
            stage="initial",
            contact_name="Dave",
            company="Anthropic",
            use_llm=False,
        )
        assert result.drafted_by == "template"

    def test_variant_a_b_different(self):
        from src.outreach.drafter import draft_with_template
        a = draft_with_template(stage="initial", contact_name="X", company="Y", variant_id="A")
        b = draft_with_template(stage="initial", contact_name="X", company="Y", variant_id="B")
        # Different templates should produce different bodies
        assert a.subject != b.subject or a.body != b.body


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

class TestRules:
    def test_daily_limit_allows_first(self, tmp_db):
        from src.outreach.rules import check_daily_limit
        ok, reason = check_daily_limit(max_per_day=5, db_path=tmp_db)
        assert ok is True

    def test_company_limit_allows_first(self, tmp_db):
        from src.outreach.rules import check_company_limit
        ok, reason = check_company_limit("Stripe", max_per_week=2, db_path=tmp_db)
        assert ok is True

    def test_duplicate_draft_blocks_second(self, tmp_db):
        from src.outreach.database import start_sequence, save_draft
        from src.outreach.rules import check_duplicate_draft
        seq = start_sequence("cx1", "dup@test.com", db_path=tmp_db)
        save_draft(
            sequence_id=seq["id"], contact_id="cx1", contact_email="dup@test.com",
            stage="initial", subject="S", body="B",
            db_path=tmp_db,
        )
        ok, reason = check_duplicate_draft(seq["id"], "initial", db_path=tmp_db)
        assert ok is False

    def test_can_send_outreach_passes_fresh(self, tmp_db):
        from src.outreach.database import start_sequence
        from src.outreach.rules import can_send_outreach
        seq = start_sequence("cx2", "fresh@test.com", company="NewCo", db_path=tmp_db)
        ok, blocks = can_send_outreach(
            contact_id="cx2", company="NewCo",
            sequence_id=seq["id"], stage="initial",
            db_path=tmp_db,
        )
        assert ok is True
        assert blocks == []


# ---------------------------------------------------------------------------
# Sequences cycle (integration)
# ---------------------------------------------------------------------------

class TestSequenceCycle:
    def test_cycle_generates_draft(self, tmp_db):
        from src.outreach.database import start_sequence, init_outreach_db
        from src.outreach.sequences import run_sequence_cycle
        init_outreach_db(tmp_db)
        start_sequence("sc1", "test@openai.com", company="OpenAI", db_path=tmp_db)
        stats = run_sequence_cycle(dry_run=False, use_llm=False, db_path=tmp_db)
        assert stats["drafts_generated"] >= 1

    def test_cycle_dry_run_no_saves(self, tmp_db):
        from src.outreach.database import start_sequence, init_outreach_db, list_drafts
        from src.outreach.sequences import run_sequence_cycle
        init_outreach_db(tmp_db)
        start_sequence("sc2", "dryrun@test.com", company="TestCo", db_path=tmp_db)
        stats = run_sequence_cycle(dry_run=True, use_llm=False, db_path=tmp_db)
        # Dry run: drafts counted but not saved
        saved = list_drafts(status="pending", db_path=tmp_db)
        assert len(saved) == 0
