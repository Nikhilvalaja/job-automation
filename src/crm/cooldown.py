"""Outreach cooldown rules — anti-spam enforcement.

Rules:
- Max 2 follow-ups per conversation (initial + follow_up_1 + follow_up_2)
- Min 3 days between any two touches to the same contact
- Min 7 days between two emails to the same company domain
- Blocked contacts: never contact
- Dead/closed conversations: never re-open

All enforcement is soft (returns bool + reason), not hard (no exceptions).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from src.crm.database import _get_conn, init_crm_db, get_contact
from src.utils.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_FOLLOW_UPS = 2          # initial + follow_up_1 + follow_up_2 = 3 total touches
MIN_CONTACT_GAP_DAYS = 3    # min days between any two touches per contact
MIN_DOMAIN_GAP_DAYS = 7     # min days between touches to same company domain
DEAD_STAGES = frozenset(("replied", "dead", "closed"))


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------

def can_contact(
    contact_id: str,
    conversation_id: str | None = None,
    db_path: Path | None = None,
) -> tuple[bool, str]:
    """Check if we're allowed to reach out to this contact.

    Returns (allowed: bool, reason: str).
    """
    init_crm_db(db_path)
    conn = _get_conn(db_path)
    try:
        # 1. Contact status check
        contact = conn.execute(
            "SELECT * FROM contacts WHERE id = ?", (contact_id,)
        ).fetchone()
        if not contact:
            return False, "contact_not_found"
        if contact["status"] == "blocked":
            return False, "contact_blocked"
        if contact["status"] == "archived":
            return False, "contact_archived"

        now_iso = datetime.utcnow().isoformat()
        now_dt = datetime.utcnow()

        # 2. Contact-level cooldown (time since last touch)
        if contact["last_contacted_at"]:
            last = datetime.fromisoformat(contact["last_contacted_at"])
            gap = (now_dt - last).days
            if gap < MIN_CONTACT_GAP_DAYS:
                days_left = MIN_CONTACT_GAP_DAYS - gap
                return False, f"cooldown:{days_left}d_remaining"

        # 3. Conversation-level checks
        if conversation_id:
            conv = conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if conv:
                if conv["stage"] in DEAD_STAGES:
                    return False, f"conversation_stage:{conv['stage']}"
                if not conv["is_active"]:
                    return False, "conversation_inactive"
                if conv["follow_up_count"] >= MAX_FOLLOW_UPS + 1:
                    return False, f"max_followups_reached:{conv['follow_up_count']}"
                # Per-conversation cooldown
                if conv["cooldown_until"] and conv["cooldown_until"] > now_iso:
                    return False, f"conversation_cooldown_until:{conv['cooldown_until'][:10]}"

        # 4. Domain-level gap check
        email = contact["email"] or ""
        if "@" in email:
            domain = email.split("@")[1]
            cutoff = (now_dt - timedelta(days=MIN_DOMAIN_GAP_DAYS)).isoformat()
            recent = conn.execute(
                """SELECT COUNT(*) AS c FROM touchpoints tp
                   JOIN contacts ct ON tp.contact_id = ct.id
                   WHERE ct.email LIKE ?
                     AND tp.direction = 'outbound'
                     AND tp.occurred_at >= ?""",
                (f"%@{domain}", cutoff),
            ).fetchone()["c"]
            if recent > 0:
                return False, f"domain_cooldown:{domain}"

        return True, "ok"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Apply cooldown
# ---------------------------------------------------------------------------

def apply_cooldown(
    conversation_id: str,
    days: int = MIN_CONTACT_GAP_DAYS,
    db_path: Path | None = None,
) -> bool:
    """Set cooldown_until for a conversation.

    Call this after sending a follow-up to prevent immediate re-send.
    """
    init_crm_db(db_path)
    conn = _get_conn(db_path)
    try:
        until = (datetime.utcnow() + timedelta(days=days)).isoformat()
        conn.execute(
            "UPDATE conversations SET cooldown_until = ?, updated_at = ? WHERE id = ?",
            (until, datetime.utcnow().isoformat(), conversation_id),
        )
        conn.commit()
        return conn.execute("SELECT changes() AS c").fetchone()["c"] > 0
    finally:
        conn.close()


def clear_cooldown(conversation_id: str, db_path: Path | None = None) -> bool:
    """Clear cooldown (e.g., after contact replies)."""
    init_crm_db(db_path)
    conn = _get_conn(db_path)
    try:
        conn.execute(
            "UPDATE conversations SET cooldown_until = NULL, updated_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), conversation_id),
        )
        conn.commit()
        return conn.execute("SELECT changes() AS c").fetchone()["c"] > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Suggested next follow-up date
# ---------------------------------------------------------------------------

def suggest_next_followup(
    stage: str,
    last_contacted: str | None = None,
) -> str:
    """Compute suggested next follow-up date based on stage.

    Delays:
      initial      →  +3 days
      follow_up_1  →  +5 days
      follow_up_2  →  +7 days (final)
      replied      →  None (no follow-up needed)
    """
    delays = {
        "initial": 3,
        "follow_up_1": 5,
        "follow_up_2": 7,
    }
    delay = delays.get(stage, MIN_CONTACT_GAP_DAYS)
    base = datetime.utcnow()
    if last_contacted:
        try:
            base = max(datetime.fromisoformat(last_contacted), base)
        except ValueError:
            pass
    return (base + timedelta(days=delay)).date().isoformat()


# ---------------------------------------------------------------------------
# Stage progression
# ---------------------------------------------------------------------------

def next_stage(current_stage: str) -> str | None:
    """Return the next follow-up stage, or None if chain is complete."""
    progression = {
        "initial": "follow_up_1",
        "follow_up_1": "follow_up_2",
        "follow_up_2": None,  # Max follow-ups reached
    }
    return progression.get(current_stage)
