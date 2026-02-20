"""Sequence orchestration — drives the daily draft generation cycle.

Flow per run:
  1. Mark cold sequences (14d no reply)
  2. Find due sequences (next_due_at <= now, status=active)
  3. For each due sequence:
     a. Check anti-spam rules
     b. Pick best A/B variant
     c. Generate draft
     d. Save draft (status=pending — human approves)
     e. Advance sequence stage + update next_due_at
  4. Return stats
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.utils.logging import get_logger

logger = get_logger(__name__)


def run_sequence_cycle(
    sender_name: str = "Nikhil",
    sender_skills: str = "Python, backend engineering, distributed systems",
    use_llm: bool = False,
    dry_run: bool = False,
    db_path: Path | None = None,
) -> dict:
    """Main entry — generate all pending drafts for due sequences."""
    from src.outreach.database import (
        get_due_sequences, advance_sequence, save_draft,
        mark_cold_sequences, get_best_variant,
    )
    from src.outreach.drafter import generate_draft
    from src.outreach.rules import can_send_outreach

    stats = {
        "cold_marked": 0,
        "sequences_checked": 0,
        "drafts_generated": 0,
        "skipped_rules": 0,
        "skipped_reasons": [],
    }

    # 1. Mark cold sequences
    if not dry_run:
        stats["cold_marked"] = mark_cold_sequences(db_path=db_path)

    # 2. Get due sequences
    due = get_due_sequences(db_path=db_path)
    stats["sequences_checked"] = len(due)
    logger.info(f"Outreach cycle: {len(due)} sequences due")

    for seq in due:
        seq_id = seq["id"]
        stage = seq["current_stage"]
        contact_id = seq["contact_id"]
        company = seq["company"] or ""
        contact_name = seq["contact_name"] or ""
        contact_email = seq["contact_email"]
        job_title = seq["job_title"] or ""

        # 3a. Anti-spam rules
        allowed, blocks = can_send_outreach(
            contact_id=contact_id,
            company=company,
            sequence_id=seq_id,
            stage=stage,
            db_path=db_path,
        )
        if not allowed:
            stats["skipped_rules"] += 1
            stats["skipped_reasons"].extend(blocks)
            logger.info(f"  Skipped {contact_email}: {blocks}")
            continue

        # 3b. Pick variant
        variant_id = get_best_variant(stage=stage, db_path=db_path)

        # 3c. Generate draft
        draft = generate_draft(
            stage=stage,
            contact_name=contact_name,
            company=company,
            sender_name=sender_name,
            skills=sender_skills,
            job_title=job_title,
            use_llm=use_llm,
            variant_id=variant_id,
        )

        logger.info(
            f"  Draft [{stage}] → {contact_email} @ {company} "
            f"(variant={variant_id}, {draft.word_count}w, by={draft.drafted_by})"
        )

        # 3d. Save draft
        if not dry_run:
            save_draft(
                sequence_id=seq_id,
                contact_id=contact_id,
                contact_email=contact_email,
                stage=stage,
                subject=draft.subject,
                body=draft.body,
                contact_name=contact_name,
                company=company,
                variant_id=variant_id,
                drafted_by=draft.drafted_by,
                db_path=db_path,
            )

            # 3e. Advance sequence
            advance_sequence(seq_id, db_path=db_path)

        stats["drafts_generated"] += 1

    return stats
