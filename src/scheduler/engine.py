"""Scheduler engine — wraps APScheduler for bot orchestration.

Provides a clean interface to schedule bots at configured intervals.
Uses BackgroundScheduler (thread-based) so bots run in background threads
while the main thread stays alive for signal handling.

SAFETY: Each bot runs in its own thread via run_safe() — one bot crashing
never affects others.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.utils.logging import get_logger

if TYPE_CHECKING:
    from bots.base import BaseBot

logger = get_logger(__name__)


class BotScheduler:
    """Manages scheduled execution of bots via APScheduler."""

    def __init__(self) -> None:
        self._scheduler = BackgroundScheduler(
            job_defaults={
                "coalesce": True,       # If a job was missed, run it once (not N times)
                "max_instances": 1,     # Never run two instances of the same bot
                "misfire_grace_time": 60,  # Allow 60s late execution
            },
        )
        self._bots: dict[str, BaseBot] = {}

    def add_interval_bot(
        self,
        bot: BaseBot,
        minutes: int,
        run_immediately: bool = True,
    ) -> None:
        """Schedule a bot to run at a fixed interval.

        Args:
            bot: The bot instance (must implement run_safe).
            minutes: Interval in minutes between runs.
            run_immediately: If True, run the bot once at startup.
        """
        self._bots[bot.name] = bot
        self._scheduler.add_job(
            bot.run_safe,
            trigger=IntervalTrigger(minutes=minutes),
            id=f"bot_{bot.name}",
            name=f"{bot.name} bot (every {minutes}m)",
            replace_existing=True,
        )
        logger.info(f"Scheduled {bot.name} bot: every {minutes} minutes")

        if run_immediately:
            # Run once right away in the scheduler thread pool
            self._scheduler.add_job(
                bot.run_safe,
                id=f"bot_{bot.name}_startup",
                name=f"{bot.name} bot (startup run)",
                replace_existing=True,
            )

    def add_daily_bot(
        self,
        bot: BaseBot,
        hour: int,
        minute: int = 0,
        run_immediately: bool = False,
    ) -> None:
        """Schedule a bot to run once per day at a specific time.

        Args:
            bot: The bot instance.
            hour: Hour of day (0-23).
            minute: Minute of hour (0-59).
            run_immediately: If True, run the bot once at startup.
        """
        self._bots[bot.name] = bot
        self._scheduler.add_job(
            bot.run_safe,
            trigger=CronTrigger(hour=hour, minute=minute),
            id=f"bot_{bot.name}",
            name=f"{bot.name} bot (daily at {hour:02d}:{minute:02d})",
            replace_existing=True,
        )
        logger.info(f"Scheduled {bot.name} bot: daily at {hour:02d}:{minute:02d}")

        if run_immediately:
            self._scheduler.add_job(
                bot.run_safe,
                id=f"bot_{bot.name}_startup",
                name=f"{bot.name} bot (startup run)",
                replace_existing=True,
            )

    def start(self) -> None:
        """Start the scheduler. All registered bots begin running."""
        # Start all bots (initialize their clients/connections)
        for name, bot in self._bots.items():
            try:
                bot.start()
                logger.info(f"Started {name} bot")
            except Exception as e:
                logger.error(f"Failed to start {name} bot: {e}", exc_info=True)

        self._scheduler.start()
        logger.info(f"Scheduler started with {len(self._bots)} bots")

    def stop(self) -> None:
        """Stop the scheduler and all bots gracefully."""
        self._scheduler.shutdown(wait=True)
        for name, bot in self._bots.items():
            try:
                bot.stop()
            except Exception as e:
                logger.error(f"Error stopping {name} bot: {e}")
        logger.info("Scheduler stopped")

    def get_jobs(self) -> list[dict]:
        """Return info about all scheduled jobs (for status display)."""
        jobs = []
        for job in self._scheduler.get_jobs():
            next_run = getattr(job, "next_run_time", None)
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": str(next_run) if next_run else "pending",
            })
        return jobs

    @property
    def running(self) -> bool:
        return self._scheduler.running
