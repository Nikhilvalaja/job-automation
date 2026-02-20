"""M16 tests — supervisor engine (today's actions, system stats, pipeline funnel)."""

from __future__ import annotations

import pytest


class TestSupervisorEngine:
    def test_get_todays_actions_returns_list(self):
        from src.supervisor.engine import get_todays_actions
        actions = get_todays_actions(max_total=20)
        assert isinstance(actions, list)

    def test_actions_have_required_fields(self):
        from src.supervisor.engine import get_todays_actions
        actions = get_todays_actions(max_total=5)
        for a in actions:
            assert "action_type" in a
            assert "priority" in a
            assert "title" in a
            assert "description" in a
            assert "action_label" in a
            assert "source" in a

    def test_actions_sorted_by_priority_desc(self):
        from src.supervisor.engine import get_todays_actions
        actions = get_todays_actions(max_total=20)
        priorities = [a["priority"] for a in actions]
        assert priorities == sorted(priorities, reverse=True)

    def test_get_system_stats_returns_dict(self):
        from src.supervisor.engine import get_system_stats
        stats = get_system_stats()
        assert isinstance(stats, dict)
        assert "generated_at" in stats

    def test_system_stats_has_all_keys(self):
        from src.supervisor.engine import get_system_stats
        stats = get_system_stats()
        expected = [
            "total_jobs", "to_apply", "applied", "interviewing",
            "signal_companies", "hot_companies",
            "crm_contacts", "outreach_pending_drafts",
        ]
        for key in expected:
            assert key in stats, f"Missing key: {key}"

    def test_get_pipeline_funnel_structure(self):
        from src.supervisor.engine import get_pipeline_funnel
        funnel = get_pipeline_funnel()
        assert isinstance(funnel, dict)
        for stage in ("discovered", "to_apply", "applied", "interviewing", "offer"):
            assert stage in funnel
            assert isinstance(funnel[stage], int)

    def test_pipeline_funnel_all_non_negative(self):
        from src.supervisor.engine import get_pipeline_funnel
        funnel = get_pipeline_funnel()
        for v in funnel.values():
            assert v >= 0

    def test_outreach_actions_included_when_drafts_exist(self, tmp_path):
        from src.outreach.database import init_outreach_db, start_sequence, save_draft
        import src.outreach.database as odb
        db = tmp_path / "out.db"
        init_outreach_db(db)
        original = odb.OUTREACH_DB_PATH
        odb.OUTREACH_DB_PATH = db
        try:
            seq = start_sequence("c1", "test@stripe.com", company="Stripe", db_path=db)
            save_draft(
                sequence_id=seq["id"], contact_id="c1", contact_email="test@stripe.com",
                stage="initial", subject="Hi from Nikhil", body="Test body here",
                db_path=db,
            )
            from src.supervisor.engine import _get_outreach_actions
            actions = _get_outreach_actions(limit=5)
            assert len(actions) >= 1
            assert actions[0].action_type == "outreach_draft"
            assert actions[0].priority >= 0.85
        finally:
            odb.OUTREACH_DB_PATH = original

    def test_signal_actions_included_when_signals_exist(self, tmp_path):
        from src.signals.database import init_signals_db, save_signal
        import src.signals.database as sdb
        db = tmp_path / "sig.db"
        init_signals_db(db)
        original = sdb.SIGNALS_DB_PATH
        sdb.SIGNALS_DB_PATH = db
        try:
            for _ in range(3):
                save_signal("Anthropic", "funding", confidence=0.9, db_path=db)
            from src.supervisor.engine import _get_signal_actions
            actions = _get_signal_actions(limit=5)
            assert len(actions) >= 1
            assert actions[0].action_type == "signal_hot"
        finally:
            sdb.SIGNALS_DB_PATH = original

    def test_actions_respect_max_total(self):
        from src.supervisor.engine import get_todays_actions
        actions = get_todays_actions(max_total=3)
        assert len(actions) <= 3

    def test_disable_jobs_flag(self):
        from src.supervisor.engine import get_todays_actions, ACTION_JOB_APPLY
        actions = get_todays_actions(include_jobs=False)
        types = [a["action_type"] for a in actions]
        assert ACTION_JOB_APPLY not in types

    def test_disable_signals_flag(self):
        from src.supervisor.engine import get_todays_actions, ACTION_SIGNAL_HOT
        actions = get_todays_actions(include_signals=False)
        types = [a["action_type"] for a in actions]
        assert ACTION_SIGNAL_HOT not in types
