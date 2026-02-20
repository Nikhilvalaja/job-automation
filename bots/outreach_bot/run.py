"""Outreach Bot — daily draft generator.

Run once per day via orchestrator or cron.

Flow:
1. Mark cold sequences (14d no reply)
2. Find sequences due today
3. Generate drafts (template or LLM)
4. Apply anti-spam rules
5. Save pending drafts for human approval
6. Telegram: "N drafts ready for your review"

CLI:
  python -m bots.outreach_bot.run [--dry-run] [--use-llm]

NEVER auto-sends. Human approval required.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from src.outreach.database import init_outreach_db, get_outreach_stats, list_drafts
from src.outreach.sequences import run_sequence_cycle
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _send_telegram(text: str) -> None:
    try:
        import requests
        from src.config import settings
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            return
        requests.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": settings.telegram_chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        logger.warning(f"Telegram send failed: {e}")


def run(
    dry_run: bool = False,
    use_llm: bool = False,
    db_path: Path | None = None,
) -> dict:
    init_outreach_db(db_path)

    logger.info(f"Outreach Bot starting (dry_run={dry_run}, use_llm={use_llm})...")

    cycle_stats = run_sequence_cycle(
        use_llm=use_llm,
        dry_run=dry_run,
        db_path=db_path,
    )

    db_stats = get_outreach_stats(db_path=db_path)
    pending = list_drafts(status="pending", limit=20, db_path=db_path)

    logger.info(
        f"Cycle done: {cycle_stats['drafts_generated']} drafts generated, "
        f"{cycle_stats['skipped_rules']} skipped, "
        f"{cycle_stats['cold_marked']} marked cold"
    )
    logger.info(
        f"DB state: {db_stats['active_sequences']} active seqs, "
        f"{db_stats['pending_drafts']} pending drafts"
    )

    # Telegram notification
    if not dry_run and cycle_stats["drafts_generated"] > 0:
        lines = [
            "*Outreach Bot Daily Summary*",
            f"Drafts ready for review: {cycle_stats['drafts_generated']}",
            f"Sequences active: {db_stats['active_sequences']}",
            f"Replied: {db_stats['replied']} | Cold: {db_stats['cold']}",
            f"Reply rate: {db_stats['reply_rate']:.0%}",
        ]
        if pending:
            lines.append("\n*Pending Drafts:*")
            for d in pending[:3]:
                lines.append(f"  • {d['contact_email']} [{d['stage']}] — {d['subject'][:50]}")
        lines.append("\n→ Open dashboard to approve/reject drafts")
        _send_telegram("\n".join(lines))

    return {
        "cycle_stats": cycle_stats,
        "db_stats": db_stats,
        "pending_drafts": pending,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Outreach Bot")
    parser.add_argument("--dry-run", action="store_true", help="Don't save drafts")
    parser.add_argument("--use-llm", action="store_true", help="Use LLM for drafting")
    args = parser.parse_args()

    result = run(dry_run=args.dry_run, use_llm=args.use_llm)
    print(f"\nDone. {result['cycle_stats']['drafts_generated']} drafts generated.")
