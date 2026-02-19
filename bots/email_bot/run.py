"""Email Bot — monitors Gmail for job application status updates.

Flow:
1. Fetch recent emails (configurable interval, default last 10 minutes)
2. Skip already-processed emails (marked with JobBot/Processed label)
3. Classify each email using the rules engine
4. If match found: update job status via PATCH /jobs/by-thread/{thread_id}
5. Apply status label + mark as processed
6. Log every action for auditability

SAFETY: Never deletes, sends, or modifies emails. Only reads and labels.
"""

from __future__ import annotations

import argparse
from datetime import date

from bots.base import BaseBot
from src.gmail.client import GmailClient
from src.gmail.labels import PROCESSED_LABEL, STATUS_LABELS, LabelManager
from src.gmail.rules import ClassificationResult, classify_email
from src.models import JobStatus, JobUpdate
from src.utils.logging import get_logger

logger = get_logger(__name__)


class EmailBot(BaseBot):
    """Bot that monitors Gmail and classifies job application emails."""

    def __init__(self, minutes_back: int = 10) -> None:
        super().__init__("email")
        self.minutes_back = minutes_back
        self._gmail: GmailClient | None = None
        self._labels: LabelManager | None = None

    def start(self) -> None:
        """Initialize Gmail client and ensure labels exist."""
        super().start()
        self._gmail = GmailClient()
        self._labels = LabelManager(self._gmail.service)
        self._labels.ensure_labels_exist()
        self.logger.info(f"Email bot ready (checking last {self.minutes_back} minutes)")

    @property
    def gmail(self) -> GmailClient:
        if self._gmail is None:
            raise RuntimeError("Email bot not started. Call start() first.")
        return self._gmail

    @property
    def labels(self) -> LabelManager:
        if self._labels is None:
            raise RuntimeError("Email bot not started. Call start() first.")
        return self._labels

    def run_once(self) -> dict:
        """Execute one cycle: fetch → classify → update → label.

        Returns:
            Summary dict with counts of processed, classified, updated, skipped.
        """
        stats = {"fetched": 0, "skipped": 0, "classified": 0, "updated": 0, "errors": 0}

        # Fetch recent emails
        query = f"is:inbox newer_than:{self.minutes_back}m"
        messages = self.gmail.get_recent_messages(query=query, max_results=50)
        stats["fetched"] = len(messages)
        self.logger.info(f"Fetched {len(messages)} recent messages")

        processed_label_id = self.labels.get_processed_label_id()

        for msg in messages:
            try:
                self._process_message(msg, processed_label_id, stats)
            except Exception as e:
                stats["errors"] += 1
                self.logger.error(f"Error processing message {msg['id']}: {e}", exc_info=True)

        self.logger.info(
            f"Cycle complete: fetched={stats['fetched']}, "
            f"classified={stats['classified']}, updated={stats['updated']}, "
            f"skipped={stats['skipped']}, errors={stats['errors']}"
        )
        return stats

    def _process_message(
        self,
        msg: dict,
        processed_label_id: str,
        stats: dict,
    ) -> None:
        """Process a single email message."""
        msg_id = msg["id"]
        thread_id = msg["thread_id"]
        subject = msg.get("subject", "")
        sender = msg.get("from", "")

        # Skip already-processed messages
        if processed_label_id in msg.get("label_ids", []):
            stats["skipped"] += 1
            return

        # Classify the email
        body = msg.get("body", "") or msg.get("snippet", "")
        result = classify_email(subject=subject, body=body)

        if result is None:
            # No match — mark as processed to avoid re-checking
            self.gmail.apply_label(msg_id, processed_label_id)
            stats["skipped"] += 1
            return

        stats["classified"] += 1
        self.logger.info(
            f"Classified: [{result.status.value}] from='{sender}' "
            f"subject='{subject[:60]}' (rule={result.rule_name}, "
            f"confidence={result.confidence})"
        )

        # Try to update the job in the backend via thread_id
        updated = self._update_job_status(thread_id, result)
        if updated:
            stats["updated"] += 1

        # Apply status label + processed label
        status_label_id = self.labels.get_status_label_id(result.status)
        if status_label_id:
            self.gmail.apply_label(msg_id, status_label_id)
        self.gmail.apply_label(msg_id, processed_label_id)

    def _update_job_status(self, thread_id: str, result: ClassificationResult) -> bool:
        """Update job status via the backend API.

        Returns True if a matching job was found and updated.
        """
        update_payload = {
            "status": result.status.value,
            "last_email_date": date.today().isoformat(),
        }

        resp = self.client.patch(
            f"/jobs/by-thread/{thread_id}",
            json=update_payload,
        )

        if resp.status_code == 200:
            job = resp.json()
            self.logger.info(
                f"Updated job {job['app_id']} ({job['company']}) "
                f"to status={result.status.value} via thread {thread_id}"
            )
            return True
        elif resp.status_code == 404:
            self.logger.debug(
                f"No job found for thread {thread_id} — "
                f"email classified as {result.status.value} but not linked to any tracked application"
            )
            return False
        else:
            self.logger.error(
                f"Backend error updating thread {thread_id}: "
                f"{resp.status_code} — {resp.text}"
            )
            return False


def main() -> None:
    """CLI entry point for manual email bot runs."""
    parser = argparse.ArgumentParser(
        prog="email-bot",
        description="Monitor Gmail for job application status updates",
    )
    parser.add_argument(
        "--minutes", "-m",
        type=int,
        default=60,
        help="How many minutes back to check (default: 60)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify emails but don't update jobs or apply labels",
    )

    args = parser.parse_args()
    bot = EmailBot(minutes_back=args.minutes)

    try:
        bot.start()

        if args.dry_run:
            # Dry run: just classify and print, don't update anything
            query = f"is:inbox newer_than:{args.minutes}m"
            messages = bot.gmail.get_recent_messages(query=query, max_results=50)
            print(f"\nFound {len(messages)} messages in the last {args.minutes} minutes:\n")

            for msg in messages:
                subject = msg.get("subject", "")
                sender = msg.get("from", "")
                body = msg.get("body", "") or msg.get("snippet", "")
                result = classify_email(subject=subject, body=body)

                status_str = result.status.value if result else "—"
                rule_str = f"({result.rule_name}, {result.confidence})" if result else ""
                print(f"  {status_str:<12} | {sender[:30]:<30} | {subject[:50]} {rule_str}")

            print(f"\n  Total: {len(messages)} emails scanned")
        else:
            stats = bot.run_once()
            print(f"\nEmail bot cycle complete:")
            print(f"  Fetched:    {stats['fetched']}")
            print(f"  Classified: {stats['classified']}")
            print(f"  Updated:    {stats['updated']}")
            print(f"  Skipped:    {stats['skipped']}")
            print(f"  Errors:     {stats['errors']}")

    except FileNotFoundError as e:
        print(f"\nSetup required: {e}")
        print("See docs/SETUP.md for Gmail OAuth configuration instructions.")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
    finally:
        bot.stop()


if __name__ == "__main__":
    main()
