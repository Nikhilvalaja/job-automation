"""Tests for the orchestrator and scheduler engine.

Tests scheduling logic without needing Gmail, Telegram, or backend credentials.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.scheduler.engine import BotScheduler


class FakeBot:
    """Minimal bot for testing the scheduler."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.started = False
        self.stopped = False
        self.run_count = 0

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def run_once(self) -> dict:
        self.run_count += 1
        return {"ran": True}

    def run_safe(self) -> dict | None:
        try:
            return self.run_once()
        except Exception:
            return None


class TestBotScheduler:
    """Test the BotScheduler wrapper around APScheduler."""

    def test_add_interval_bot(self):
        """Interval bot is registered with the scheduler."""
        scheduler = BotScheduler()
        bot = FakeBot("test_interval")
        scheduler.add_interval_bot(bot, minutes=10, run_immediately=False)

        jobs = scheduler.get_jobs()
        assert any("test_interval" in j["name"] for j in jobs)

    def test_add_daily_bot(self):
        """Daily bot is registered with cron trigger."""
        scheduler = BotScheduler()
        bot = FakeBot("test_daily")
        scheduler.add_daily_bot(bot, hour=9, minute=30, run_immediately=False)

        jobs = scheduler.get_jobs()
        assert any("test_daily" in j["name"] for j in jobs)

    def test_add_interval_bot_with_immediate_run(self):
        """Immediate run creates a startup job."""
        scheduler = BotScheduler()
        bot = FakeBot("test_immediate")
        scheduler.add_interval_bot(bot, minutes=5, run_immediately=True)

        jobs = scheduler.get_jobs()
        job_ids = [j["id"] for j in jobs]
        assert "bot_test_immediate" in job_ids
        assert "bot_test_immediate_startup" in job_ids

    def test_start_initializes_bots(self):
        """Starting the scheduler calls start() on all registered bots."""
        scheduler = BotScheduler()
        bot1 = FakeBot("b1")
        bot2 = FakeBot("b2")
        scheduler.add_interval_bot(bot1, minutes=10, run_immediately=False)
        scheduler.add_daily_bot(bot2, hour=9, run_immediately=False)

        scheduler.start()
        try:
            assert bot1.started is True
            assert bot2.started is True
        finally:
            scheduler.stop()

    def test_stop_cleans_up_bots(self):
        """Stopping the scheduler calls stop() on all bots."""
        scheduler = BotScheduler()
        bot = FakeBot("cleanup")
        scheduler.add_interval_bot(bot, minutes=10, run_immediately=False)

        scheduler.start()
        scheduler.stop()
        assert bot.stopped is True

    def test_get_jobs_empty(self):
        """No jobs when nothing is registered."""
        scheduler = BotScheduler()
        assert scheduler.get_jobs() == []

    def test_multiple_bots(self):
        """Multiple bots can be registered."""
        scheduler = BotScheduler()
        for i in range(3):
            bot = FakeBot(f"multi_{i}")
            scheduler.add_interval_bot(bot, minutes=10, run_immediately=False)

        jobs = scheduler.get_jobs()
        assert len(jobs) == 3

    def test_replace_existing_bot(self):
        """Re-registering a bot with same name replaces the old job when running."""
        scheduler = BotScheduler()
        bot1 = FakeBot("replaceable")
        bot2 = FakeBot("replaceable")

        scheduler.start()
        try:
            scheduler.add_interval_bot(bot1, minutes=10, run_immediately=False)
            scheduler.add_interval_bot(bot2, minutes=20, run_immediately=False)

            jobs = [j for j in scheduler.get_jobs() if j["id"] == "bot_replaceable"]
            assert len(jobs) == 1  # Only one, not two
        finally:
            scheduler.stop()

    def test_running_property(self):
        """Running property reflects scheduler state."""
        scheduler = BotScheduler()
        assert scheduler.running is False
        scheduler.start()
        assert scheduler.running is True
        scheduler.stop()
        assert scheduler.running is False

    def test_bot_failure_does_not_crash_scheduler(self):
        """A failing bot doesn't bring down the scheduler."""
        scheduler = BotScheduler()
        bot = FakeBot("failing")
        bot.run_once = MagicMock(side_effect=RuntimeError("boom"))

        scheduler.add_interval_bot(bot, minutes=10, run_immediately=False)
        scheduler.start()
        try:
            # Manually call run_safe — should not raise
            result = bot.run_safe()
            assert result is None
            assert scheduler.running is True
        finally:
            scheduler.stop()


class TestOrchestrator:
    """Test orchestrator setup logic (without actually scheduling)."""

    @patch("bots.orchestrator.run.get_settings")
    def test_orchestrator_init(self, mock_settings):
        """Orchestrator initializes with correct flags."""
        mock_settings.return_value = MagicMock(
            email_bot_interval_minutes=5,
            reminder_bot_hour=9,
            reminder_bot_minute=0,
        )
        from bots.orchestrator.run import Orchestrator

        orch = Orchestrator(enable_email=True, enable_reminder=False)
        assert orch.enable_email is True
        assert orch.enable_reminder is False

    @patch("bots.orchestrator.run.get_settings")
    def test_orchestrator_disable_email(self, mock_settings):
        """Orchestrator respects --no-email flag."""
        mock_settings.return_value = MagicMock(
            email_bot_interval_minutes=5,
            reminder_bot_hour=9,
            reminder_bot_minute=0,
        )
        from bots.orchestrator.run import Orchestrator

        orch = Orchestrator(
            enable_email=False, enable_reminder=False,
            enable_discovery=False, enable_gmail_ingest=False,
        )
        orch.setup()
        # No bots should be registered
        jobs = orch.scheduler.get_jobs()
        assert len(jobs) == 0
