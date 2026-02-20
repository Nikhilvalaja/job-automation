"""Orchestrator — SuperBot that schedules and manages all other bots.

Runs as a long-lived process. Starts APScheduler with:
- Email Bot: every N minutes (default 5)
- Reminder Bot: daily at configured time (default 9:00 AM)

Future bots (Discovery, Resume) will be added here when implemented.

Usage:
    python -m bots.orchestrator.run              # Run with default config
    python -m bots.orchestrator.run --no-email    # Skip email bot
    python -m bots.orchestrator.run --no-reminder # Skip reminder bot
    python -m bots.orchestrator.run --run-now     # Run all bots once immediately

SAFETY: Orchestrator never touches data directly. It only schedules bots
that individually follow the 10 safety rules from BaseBot.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time

from src.config import get_settings
from src.notifications.telegram import TelegramNotifier
from src.scheduler.engine import BotScheduler
from src.utils.logging import get_logger

logger = get_logger(__name__)


class Orchestrator:
    """Central scheduler that manages all automation bots."""

    def __init__(
        self,
        enable_email: bool = True,
        enable_reminder: bool = True,
        enable_discovery: bool = True,
        run_immediately: bool = False,
    ) -> None:
        self.settings = get_settings()
        self.scheduler = BotScheduler()
        self.enable_email = enable_email
        self.enable_reminder = enable_reminder
        self.enable_discovery = enable_discovery
        self.run_immediately = run_immediately
        self._notifier: TelegramNotifier | None = None
        self._stopped = False

    def setup(self) -> None:
        """Register all enabled bots with the scheduler."""
        if self.enable_email:
            self._setup_email_bot()

        if self.enable_reminder:
            self._setup_reminder_bot()

        if self.enable_discovery:
            self._setup_discovery_bot()

        # Telegram for orchestrator-level alerts
        self._notifier = TelegramNotifier()

    def _setup_email_bot(self) -> None:
        """Register the email bot for interval scheduling."""
        try:
            from bots.email_bot.run import EmailBot

            bot = EmailBot(minutes_back=self.settings.email_bot_interval_minutes)
            self.scheduler.add_interval_bot(
                bot,
                minutes=self.settings.email_bot_interval_minutes,
                run_immediately=self.run_immediately,
            )
            logger.info(
                f"Email bot registered: every {self.settings.email_bot_interval_minutes} min"
            )
        except Exception as e:
            logger.error(f"Failed to register email bot: {e}", exc_info=True)

    def _setup_reminder_bot(self) -> None:
        """Register the reminder bot for daily scheduling."""
        try:
            from bots.reminder_bot.run import ReminderBot

            bot = ReminderBot()
            self.scheduler.add_daily_bot(
                bot,
                hour=self.settings.reminder_bot_hour,
                minute=self.settings.reminder_bot_minute,
                run_immediately=self.run_immediately,
            )
            logger.info(
                f"Reminder bot registered: daily at "
                f"{self.settings.reminder_bot_hour:02d}:{self.settings.reminder_bot_minute:02d}"
            )
        except Exception as e:
            logger.error(f"Failed to register reminder bot: {e}", exc_info=True)

    def _setup_discovery_bot(self) -> None:
        """Register the discovery bot for interval scheduling."""
        try:
            from bots.discovery_bot.run import DiscoveryBot

            bot = DiscoveryBot()
            self.scheduler.add_interval_bot(
                bot,
                minutes=self.settings.discovery_bot_interval_minutes,
                run_immediately=self.run_immediately,
            )
            logger.info(
                f"Discovery bot registered: every {self.settings.discovery_bot_interval_minutes} min"
            )
        except Exception as e:
            logger.error(f"Failed to register discovery bot: {e}", exc_info=True)

    def start(self) -> None:
        """Start the orchestrator and all scheduled bots."""
        logger.info("Orchestrator starting...")
        self.setup()
        self.scheduler.start()

        # Send startup notification
        if self._notifier and self._notifier.is_configured():
            jobs = self.scheduler.get_jobs()
            bot_list = "\n".join(f"  - {j['name']}" for j in jobs if "startup" not in j["id"])
            self._notifier.send_message(
                f"*Orchestrator Started*\n\nScheduled bots:\n{bot_list}"
            )

        self._print_status()
        logger.info("Orchestrator running. Press Ctrl+C to stop.")

    def stop(self) -> None:
        """Stop the orchestrator gracefully."""
        if self._stopped:
            return
        self._stopped = True

        logger.info("Orchestrator shutting down...")
        self.scheduler.stop()

        if self._notifier and self._notifier.is_configured():
            self._notifier.send_message("*Orchestrator Stopped*\n\nAll bots have been shut down.")

        logger.info("Orchestrator stopped.")

    def run_forever(self) -> None:
        """Block the main thread until interrupted."""
        # Handle Ctrl+C and SIGTERM gracefully
        def _signal_handler(signum, frame):
            logger.info(f"Received signal {signum}")
            self.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        try:
            while not self._stopped:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def _print_status(self) -> None:
        """Print current scheduler status to console."""
        jobs = self.scheduler.get_jobs()
        print("\n  Orchestrator Running")
        print("  " + "=" * 50)
        for job in jobs:
            if "startup" not in job["id"]:
                print(f"  {job['name']:<40} next: {job['next_run']}")
        print("  " + "=" * 50)
        print("  Press Ctrl+C to stop.\n")


def main() -> None:
    """CLI entry point for the orchestrator."""
    parser = argparse.ArgumentParser(
        prog="orchestrator",
        description="Central scheduler for all job automation bots",
    )
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="Disable the email bot",
    )
    parser.add_argument(
        "--no-reminder",
        action="store_true",
        help="Disable the reminder bot",
    )
    parser.add_argument(
        "--no-discovery",
        action="store_true",
        help="Disable the discovery bot",
    )
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Run all bots once immediately at startup",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show scheduled jobs and exit",
    )

    args = parser.parse_args()

    # Fix Windows console encoding
    import io
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    orchestrator = Orchestrator(
        enable_email=not args.no_email,
        enable_reminder=not args.no_reminder,
        enable_discovery=not args.no_discovery,
        run_immediately=args.run_now,
    )

    if args.status:
        orchestrator.setup()
        orchestrator.scheduler.start()
        orchestrator._print_status()
        orchestrator.stop()
        return

    try:
        orchestrator.start()
        orchestrator.run_forever()
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
    finally:
        orchestrator.stop()


if __name__ == "__main__":
    main()
