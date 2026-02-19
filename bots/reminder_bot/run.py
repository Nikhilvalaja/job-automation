"""Reminder Bot — detects stale applications and sends Telegram alerts.

Flow:
1. Fetch all jobs with status "Applied" from the backend
2. For each job: check if date_applied is older than threshold (default 7 days)
3. Mark stale jobs as "No Reply" via PATCH /jobs/{app_id}
4. Send a single Telegram summary with all stale jobs
5. Log every action for auditability

SAFETY: Never deletes data. Only updates status from Applied → No Reply.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta

from bots.base import BaseBot
from src.config import get_settings
from src.notifications.telegram import TelegramNotifier
from src.utils.logging import get_logger

logger = get_logger(__name__)


class ReminderBot(BaseBot):
    """Bot that detects stale applications and sends follow-up reminders."""

    def __init__(self, threshold_days: int | None = None) -> None:
        super().__init__("reminder")
        settings = get_settings()
        self.threshold_days = threshold_days or settings.followup_threshold_days
        self._notifier: TelegramNotifier | None = None

    def start(self) -> None:
        super().start()
        self._notifier = TelegramNotifier()
        if self._notifier.is_configured():
            self.logger.info("Telegram notifications enabled")
        else:
            self.logger.warning("Telegram not configured — reminders will only log, not notify")

    @property
    def notifier(self) -> TelegramNotifier:
        if self._notifier is None:
            raise RuntimeError("Reminder bot not started. Call start() first.")
        return self._notifier

    def run_once(self) -> dict:
        """Check for stale applications and send reminders.

        Returns:
            Summary dict with counts.
        """
        stats = {"checked": 0, "stale": 0, "updated": 0, "notified": False}

        # Fetch all "Applied" jobs
        resp = self.client.get("/jobs", params={"status": "Applied"})
        if resp.status_code != 200:
            self.logger.error(f"Failed to fetch jobs: {resp.status_code}")
            return stats

        jobs = resp.json().get("jobs", [])
        stats["checked"] = len(jobs)
        self.logger.info(f"Checking {len(jobs)} jobs with status 'Applied'")

        cutoff = date.today() - timedelta(days=self.threshold_days)
        stale_jobs = []

        for job in jobs:
            # Use last_email_date if available, otherwise date_applied
            check_date_str = job.get("last_email_date") or job.get("date_applied") or ""
            if not check_date_str:
                continue

            try:
                check_date = date.fromisoformat(check_date_str)
            except ValueError:
                self.logger.debug(f"Skipping job {job['app_id']}: invalid date '{check_date_str}'")
                continue

            if check_date <= cutoff:
                stale_jobs.append(job)
                stats["stale"] += 1

                # Update status to "No Reply"
                update_resp = self.client.patch(
                    f"/jobs/{job['app_id']}",
                    json={"status": "No Reply"},
                )
                if update_resp.status_code == 200:
                    stats["updated"] += 1
                    self.logger.info(
                        f"Marked stale: {job['company']} / {job['role']} "
                        f"(applied {check_date_str}, {(date.today() - check_date).days} days ago)"
                    )
                else:
                    self.logger.error(
                        f"Failed to update {job['app_id']}: {update_resp.status_code}"
                    )

        # Send Telegram notification
        if stale_jobs and self.notifier.is_configured():
            sent = self.notifier.send_followup_reminder(stale_jobs)
            stats["notified"] = sent

        self.logger.info(
            f"Reminder cycle complete: checked={stats['checked']}, "
            f"stale={stats['stale']}, updated={stats['updated']}, "
            f"notified={stats['notified']}"
        )
        return stats


def main() -> None:
    """CLI entry point for manual reminder bot runs."""
    parser = argparse.ArgumentParser(
        prog="reminder-bot",
        description="Check for stale job applications and send reminders",
    )
    parser.add_argument(
        "--days", "-d",
        type=int,
        default=None,
        help=f"Days threshold for follow-up (default: from config)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show stale jobs but don't update status or send notifications",
    )

    args = parser.parse_args()
    bot = ReminderBot(threshold_days=args.days)

    # Fix Windows console encoding
    import sys, io
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    try:
        bot.start()

        if args.dry_run:
            # Dry run: just list stale jobs
            resp = bot.client.get("/jobs", params={"status": "Applied"})
            if resp.status_code != 200:
                print(f"Failed to fetch jobs: {resp.status_code}")
                return

            jobs = resp.json().get("jobs", [])
            cutoff = date.today() - timedelta(days=bot.threshold_days)
            stale = []

            for job in jobs:
                check_date_str = job.get("last_email_date") or job.get("date_applied") or ""
                if not check_date_str:
                    continue
                try:
                    check_date = date.fromisoformat(check_date_str)
                except ValueError:
                    continue
                if check_date <= cutoff:
                    days_ago = (date.today() - check_date).days
                    stale.append((job, days_ago))

            print(f"\nChecked {len(jobs)} 'Applied' jobs (threshold: {bot.threshold_days} days):\n")
            if stale:
                print(f"  {'Company':<20} | {'Role':<25} | {'Applied':<12} | Days Ago")
                print(f"  {'-'*20}-+-{'-'*25}-+-{'-'*12}-+-{'-'*8}")
                for job, days in stale:
                    applied = job.get("date_applied", "?")
                    print(f"  {job['company']:<20} | {job['role']:<25} | {applied:<12} | {days}")
                print(f"\n  {len(stale)} stale applications found (would mark as 'No Reply')")
            else:
                print("  No stale applications found. All good!")
        else:
            stats = bot.run_once()
            print(f"\nReminder bot cycle complete:")
            print(f"  Checked:  {stats['checked']} Applied jobs")
            print(f"  Stale:    {stats['stale']} (> {bot.threshold_days} days)")
            print(f"  Updated:  {stats['updated']} → No Reply")
            print(f"  Notified: {'Yes' if stats['notified'] else 'No (Telegram not configured)'}")

    except httpx.ConnectError:
        import httpx
        print(f"\nCould not connect to backend at {bot.backend_url}.")
        print("Make sure the backend is running: uvicorn backend.main:app --reload")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
    finally:
        bot.stop()


if __name__ == "__main__":
    main()
