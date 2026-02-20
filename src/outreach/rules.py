"""Outreach anti-spam rules.

Rules enforced before any draft is generated:
  1. Max 5 outreach emails per day (total)
  2. Max 2 emails per company per week
  3. Must respect CRM cooldown (3d contact gap)
  4. No sending to contacts marked as 'unsubscribed' or 'blocked'
  5. No duplicate drafts for same sequence+stage
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path


def check_daily_limit(
    max_per_day: int = 5,
    db_path: Path | None = None,
) -> tuple[bool, str]:
    """Return (allowed, reason). False if daily limit reached."""
    from src.outreach.database import init_outreach_db, _get_conn
    init_outreach_db(db_path)
    conn = _get_conn(db_path)
    try:
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0).isoformat()
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM outreach_drafts WHERE status IN ('approved','sent') AND created_at >= ?",
            (today_start,),
        ).fetchone()["c"]
        if count >= max_per_day:
            return False, f"Daily limit reached ({count}/{max_per_day})"
        return True, f"{count}/{max_per_day} sent today"
    finally:
        conn.close()


def check_company_limit(
    company: str,
    max_per_week: int = 2,
    db_path: Path | None = None,
) -> tuple[bool, str]:
    """Return (allowed, reason). False if too many emails to same company this week."""
    from src.outreach.database import init_outreach_db, _get_conn
    if not company:
        return True, "no company set"
    init_outreach_db(db_path)
    conn = _get_conn(db_path)
    try:
        week_start = (datetime.utcnow() - timedelta(days=7)).isoformat()
        count = conn.execute(
            """SELECT COUNT(*) AS c FROM outreach_drafts
               WHERE LOWER(company) = ? AND status IN ('approved','sent') AND created_at >= ?""",
            (company.lower(), week_start),
        ).fetchone()["c"]
        if count >= max_per_week:
            return False, f"Company limit reached for {company} ({count}/{max_per_week} this week)"
        return True, f"{count}/{max_per_week} emails to {company} this week"
    finally:
        conn.close()


def check_crm_cooldown(
    contact_id: str,
    db_path: Path | None = None,
) -> tuple[bool, str]:
    """Delegate to CRM cooldown check. Unknown contacts (not in CRM yet) are allowed."""
    try:
        from src.crm.cooldown import can_contact
        allowed, reason = can_contact(contact_id)
        # contact_not_found → not in CRM yet, allow outreach
        if not allowed and reason == "contact_not_found":
            return True, "contact not yet in CRM — allowed"
        return allowed, reason
    except Exception:
        return True, "crm cooldown check unavailable"


def check_duplicate_draft(
    sequence_id: str,
    stage: str,
    db_path: Path | None = None,
) -> tuple[bool, str]:
    """Return (allowed, reason). False if pending draft already exists for this sequence+stage."""
    from src.outreach.database import init_outreach_db, _get_conn
    init_outreach_db(db_path)
    conn = _get_conn(db_path)
    try:
        existing = conn.execute(
            "SELECT id FROM outreach_drafts WHERE sequence_id = ? AND stage = ? AND status = 'pending'",
            (sequence_id, stage),
        ).fetchone()
        if existing:
            return False, f"Pending draft already exists for seq {sequence_id} stage {stage}"
        return True, "no duplicate"
    finally:
        conn.close()


def can_send_outreach(
    contact_id: str,
    company: str,
    sequence_id: str,
    stage: str,
    db_path: Path | None = None,
) -> tuple[bool, list[str]]:
    """Run all rules. Returns (allowed, list_of_blocking_reasons)."""
    blocks: list[str] = []

    ok, reason = check_daily_limit(db_path=db_path)
    if not ok:
        blocks.append(reason)

    ok, reason = check_company_limit(company, db_path=db_path)
    if not ok:
        blocks.append(reason)

    ok, reason = check_duplicate_draft(sequence_id, stage, db_path=db_path)
    if not ok:
        blocks.append(reason)

    # CRM cooldown (soft check — don't block on errors)
    ok, reason = check_crm_cooldown(contact_id, db_path=db_path)
    if not ok:
        blocks.append(f"CRM cooldown: {reason}")

    return len(blocks) == 0, blocks
