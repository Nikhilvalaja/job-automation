"""CRM database — contacts, conversations, touchpoints.

Schema:
  contacts       — people (name, email, company, role, status)
  conversations  — job threads (stage, cooldown, next follow-up)
  touchpoints    — every interaction logged (sent, received, noted)

Design principles:
- Dedup by email (UNIQUE constraint)
- Soft-delete only — never hard-delete contacts
- Cooldown enforced at DB level (cooldown_until column)
- All timestamps in UTC ISO format
- WAL mode for concurrent access
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from src.utils.logging import get_logger

logger = get_logger(__name__)

CRM_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "crm.db"


def _get_conn(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or CRM_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_crm_db(db_path: Path | None = None) -> None:
    """Initialize CRM schema. Idempotent."""
    conn = _get_conn(db_path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS contacts (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                email TEXT UNIQUE NOT NULL,
                company TEXT DEFAULT '',
                role TEXT DEFAULT '',            -- "recruiter", "hiring_manager", "engineer", "unknown"
                source TEXT DEFAULT 'manual',   -- "gmail", "linkedin", "manual"
                status TEXT DEFAULT 'active',   -- "active", "cold", "blocked", "archived"
                tags TEXT DEFAULT '[]',          -- JSON array of tags
                notes TEXT DEFAULT '',
                linkedin_url TEXT DEFAULT '',
                last_contacted_at TEXT DEFAULT NULL,
                first_contacted_at TEXT DEFAULT NULL,
                total_touchpoints INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                contact_id TEXT NOT NULL,
                job_id TEXT DEFAULT NULL,        -- link to discovered_jobs
                subject TEXT DEFAULT '',
                stage TEXT DEFAULT 'initial',    -- "initial", "follow_up_1", "follow_up_2", "replied", "dead", "closed"
                direction TEXT DEFAULT 'outbound', -- "outbound" or "inbound"
                last_message_at TEXT DEFAULT NULL,
                next_follow_up TEXT DEFAULT NULL,
                cooldown_until TEXT DEFAULT NULL,
                follow_up_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS touchpoints (
                id TEXT PRIMARY KEY,
                contact_id TEXT NOT NULL,
                conversation_id TEXT DEFAULT NULL,
                type TEXT NOT NULL,              -- "email_sent", "email_received", "note", "call", "meeting"
                subject TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                raw_snippet TEXT DEFAULT '',
                gmail_thread_id TEXT DEFAULT '',
                gmail_message_id TEXT DEFAULT '',
                direction TEXT DEFAULT 'outbound',
                sentiment TEXT DEFAULT 'neutral', -- "positive", "neutral", "negative"
                occurred_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_contacts_email   ON contacts(email);
            CREATE INDEX IF NOT EXISTS idx_contacts_company ON contacts(company);
            CREATE INDEX IF NOT EXISTS idx_contacts_status  ON contacts(status);
            CREATE INDEX IF NOT EXISTS idx_convs_contact    ON conversations(contact_id);
            CREATE INDEX IF NOT EXISTS idx_convs_job        ON conversations(job_id);
            CREATE INDEX IF NOT EXISTS idx_convs_stage      ON conversations(stage);
            CREATE INDEX IF NOT EXISTS idx_convs_followup   ON conversations(next_follow_up);
            CREATE INDEX IF NOT EXISTS idx_tp_contact       ON touchpoints(contact_id);
            CREATE INDEX IF NOT EXISTS idx_tp_thread        ON touchpoints(gmail_thread_id);
            CREATE INDEX IF NOT EXISTS idx_tp_occurred      ON touchpoints(occurred_at);
        """)
        conn.commit()
        logger.debug("CRM DB initialized")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Contact CRUD
# ---------------------------------------------------------------------------

def upsert_contact(
    email: str,
    name: str = "",
    company: str = "",
    role: str = "unknown",
    source: str = "manual",
    tags: list[str] | None = None,
    notes: str = "",
    linkedin_url: str = "",
    db_path: Path | None = None,
) -> dict:
    """Insert or update a contact by email (UNIQUE key).

    Returns the contact dict (with id).
    """
    conn = _get_conn(db_path)
    try:
        init_crm_db(db_path)
        now = datetime.utcnow().isoformat()

        # Check if exists
        existing = conn.execute(
            "SELECT * FROM contacts WHERE email = ?", (email,)
        ).fetchone()

        if existing:
            # Update non-empty fields only
            updates = {"updated_at": now}
            if name:
                updates["name"] = name
            if company:
                updates["company"] = company
            if role and role != "unknown":
                updates["role"] = role
            if tags is not None:
                updates["tags"] = json.dumps(tags)
            if notes:
                updates["notes"] = notes
            if linkedin_url:
                updates["linkedin_url"] = linkedin_url

            set_clause = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(
                f"UPDATE contacts SET {set_clause} WHERE email = ?",
                (*updates.values(), email),
            )
            conn.commit()
            contact_id = existing["id"]
        else:
            contact_id = str(uuid.uuid4())[:8]
            conn.execute(
                """INSERT INTO contacts
                   (id, name, email, company, role, source, tags, notes,
                    linkedin_url, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    contact_id, name or email.split("@")[0], email,
                    company, role, source,
                    json.dumps(tags or []), notes, linkedin_url, now, now,
                ),
            )
            conn.commit()
            logger.info(f"New contact: {name or email} ({company})")

        row = conn.execute(
            "SELECT * FROM contacts WHERE id = ?", (contact_id,)
        ).fetchone()
        result = dict(row)
        result["tags"] = json.loads(result.get("tags", "[]"))
        return result
    finally:
        conn.close()


def get_contact(contact_id: str, db_path: Path | None = None) -> dict | None:
    conn = _get_conn(db_path)
    try:
        init_crm_db(db_path)
        row = conn.execute(
            "SELECT * FROM contacts WHERE id = ?", (contact_id,)
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["tags"] = json.loads(result.get("tags", "[]"))
        return result
    finally:
        conn.close()


def get_contact_by_email(email: str, db_path: Path | None = None) -> dict | None:
    conn = _get_conn(db_path)
    try:
        init_crm_db(db_path)
        row = conn.execute(
            "SELECT * FROM contacts WHERE email = ?", (email,)
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["tags"] = json.loads(result.get("tags", "[]"))
        return result
    finally:
        conn.close()


def list_contacts(
    status: str | None = None,
    company: str | None = None,
    role: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db_path: Path | None = None,
) -> list[dict]:
    conn = _get_conn(db_path)
    try:
        init_crm_db(db_path)
        query = "SELECT * FROM contacts"
        params: list = []
        conditions = []

        if status:
            conditions.append("status = ?")
            params.append(status)
        if company:
            conditions.append("company LIKE ?")
            params.append(f"%{company}%")
        if role:
            conditions.append("role = ?")
            params.append(role)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY last_contacted_at DESC NULLS LAST, created_at DESC"
        query += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            r = dict(row)
            r["tags"] = json.loads(r.get("tags", "[]"))
            results.append(r)
        return results
    finally:
        conn.close()


def update_contact_status(
    contact_id: str,
    status: str,
    db_path: Path | None = None,
) -> bool:
    """Update contact status: active, cold, blocked, archived."""
    valid = ("active", "cold", "blocked", "archived")
    if status not in valid:
        return False
    conn = _get_conn(db_path)
    try:
        init_crm_db(db_path)
        now = datetime.utcnow().isoformat()
        conn.execute(
            "UPDATE contacts SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, contact_id),
        )
        rows = conn.execute("SELECT changes() AS c").fetchone()["c"]
        conn.commit()
        return rows > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Conversation CRUD
# ---------------------------------------------------------------------------

def create_conversation(
    contact_id: str,
    subject: str = "",
    job_id: str | None = None,
    stage: str = "initial",
    direction: str = "outbound",
    db_path: Path | None = None,
) -> dict:
    """Create a new conversation thread for a contact."""
    conn = _get_conn(db_path)
    try:
        init_crm_db(db_path)
        conv_id = str(uuid.uuid4())[:8]
        now = datetime.utcnow().isoformat()
        conn.execute(
            """INSERT INTO conversations
               (id, contact_id, job_id, subject, stage, direction, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (conv_id, contact_id, job_id, subject, stage, direction, now, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conv_id,)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def get_or_create_conversation(
    contact_id: str,
    job_id: str | None = None,
    subject: str = "",
    db_path: Path | None = None,
) -> dict:
    """Get an existing active conversation or create one."""
    conn = _get_conn(db_path)
    try:
        init_crm_db(db_path)
        # Look for active conversation with same contact + job
        query = "SELECT * FROM conversations WHERE contact_id = ? AND is_active = 1"
        params: list = [contact_id]
        if job_id:
            query += " AND job_id = ?"
            params.append(job_id)
        row = conn.execute(query, params).fetchone()
        if row:
            return dict(row)
    finally:
        conn.close()
    # Create new
    return create_conversation(contact_id, subject=subject, job_id=job_id, db_path=db_path)


def update_conversation_stage(
    conv_id: str,
    stage: str,
    next_follow_up: str | None = None,
    db_path: Path | None = None,
) -> bool:
    """Update conversation stage and optional next follow-up date."""
    valid = ("initial", "follow_up_1", "follow_up_2", "replied", "dead", "closed")
    if stage not in valid:
        return False
    conn = _get_conn(db_path)
    try:
        init_crm_db(db_path)
        now = datetime.utcnow().isoformat()
        conn.execute(
            """UPDATE conversations
               SET stage = ?, next_follow_up = ?, updated_at = ?
               WHERE id = ?""",
            (stage, next_follow_up, now, conv_id),
        )
        rows = conn.execute("SELECT changes() AS c").fetchone()["c"]
        conn.commit()
        return rows > 0
    finally:
        conn.close()


def get_conversations(
    contact_id: str | None = None,
    stage: str | None = None,
    active_only: bool = True,
    db_path: Path | None = None,
) -> list[dict]:
    """List conversations, optionally filtered."""
    conn = _get_conn(db_path)
    try:
        init_crm_db(db_path)
        query = "SELECT * FROM conversations"
        params: list = []
        conditions = []

        if active_only:
            conditions.append("is_active = 1")
        if contact_id:
            conditions.append("contact_id = ?")
            params.append(contact_id)
        if stage:
            conditions.append("stage = ?")
            params.append(stage)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY last_message_at DESC NULLS LAST"

        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Touchpoint CRUD
# ---------------------------------------------------------------------------

def log_touchpoint(
    contact_id: str,
    type: str,
    subject: str = "",
    summary: str = "",
    raw_snippet: str = "",
    conversation_id: str | None = None,
    gmail_thread_id: str = "",
    gmail_message_id: str = "",
    direction: str = "outbound",
    sentiment: str = "neutral",
    occurred_at: str | None = None,
    db_path: Path | None = None,
) -> dict:
    """Log a touchpoint (email sent, email received, note, call, etc.)."""
    conn = _get_conn(db_path)
    try:
        init_crm_db(db_path)
        now = datetime.utcnow().isoformat()
        tp_id = str(uuid.uuid4())[:8]
        occurred = occurred_at or now

        conn.execute(
            """INSERT INTO touchpoints
               (id, contact_id, conversation_id, type, subject, summary,
                raw_snippet, gmail_thread_id, gmail_message_id,
                direction, sentiment, occurred_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                tp_id, contact_id, conversation_id, type, subject,
                summary, raw_snippet[:500], gmail_thread_id, gmail_message_id,
                direction, sentiment, occurred, now,
            ),
        )

        # Update contact's last_contacted_at and touch count
        if direction == "outbound":
            conn.execute(
                """UPDATE contacts SET
                   last_contacted_at = ?,
                   first_contacted_at = COALESCE(first_contacted_at, ?),
                   total_touchpoints = total_touchpoints + 1,
                   updated_at = ?
                   WHERE id = ?""",
                (occurred, occurred, now, contact_id),
            )
        else:
            # Inbound — still counts as a touchpoint
            conn.execute(
                """UPDATE contacts SET
                   total_touchpoints = total_touchpoints + 1,
                   updated_at = ?
                   WHERE id = ?""",
                (now, contact_id),
            )

        # Update conversation last_message_at + follow-up count if outbound
        if conversation_id:
            if direction == "outbound":
                conn.execute(
                    """UPDATE conversations SET
                       last_message_at = ?,
                       follow_up_count = follow_up_count + 1,
                       updated_at = ?
                       WHERE id = ?""",
                    (occurred, now, conversation_id),
                )
            else:
                conn.execute(
                    """UPDATE conversations SET
                       last_message_at = ?,
                       stage = CASE WHEN stage != 'replied' THEN 'replied' ELSE stage END,
                       updated_at = ?
                       WHERE id = ?""",
                    (occurred, now, conversation_id),
                )

        conn.commit()
        row = conn.execute(
            "SELECT * FROM touchpoints WHERE id = ?", (tp_id,)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def get_touchpoints(
    contact_id: str | None = None,
    conversation_id: str | None = None,
    gmail_thread_id: str | None = None,
    limit: int = 50,
    db_path: Path | None = None,
) -> list[dict]:
    """Get touchpoints, filtered by contact, conversation, or thread."""
    conn = _get_conn(db_path)
    try:
        init_crm_db(db_path)
        query = "SELECT * FROM touchpoints"
        params: list = []
        conditions = []

        if contact_id:
            conditions.append("contact_id = ?")
            params.append(contact_id)
        if conversation_id:
            conditions.append("conversation_id = ?")
            params.append(conversation_id)
        if gmail_thread_id:
            conditions.append("gmail_thread_id = ?")
            params.append(gmail_thread_id)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += f" ORDER BY occurred_at DESC LIMIT {limit}"

        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Today's Actions query
# ---------------------------------------------------------------------------

def get_todays_actions(
    overdue_days: int = 1,
    db_path: Path | None = None,
) -> list[dict]:
    """Get contacts/conversations that need action today.

    Returns conversations where:
    - next_follow_up <= today
    - stage not in (replied, dead, closed)
    - cooldown_until is NULL or past
    - contact is active (not blocked/archived)
    """
    conn = _get_conn(db_path)
    try:
        init_crm_db(db_path)
        today = datetime.utcnow().date().isoformat()
        rows = conn.execute(
            """SELECT
                c.id AS conv_id,
                c.stage,
                c.next_follow_up,
                c.follow_up_count,
                c.last_message_at,
                c.job_id,
                ct.id AS contact_id,
                ct.name,
                ct.email,
                ct.company,
                ct.role
               FROM conversations c
               JOIN contacts ct ON c.contact_id = ct.id
               WHERE c.is_active = 1
                 AND c.stage NOT IN ('replied', 'dead', 'closed')
                 AND ct.status NOT IN ('blocked', 'archived')
                 AND (
                   c.next_follow_up <= ?
                   OR (c.next_follow_up IS NULL AND c.last_message_at <= ?)
                 )
                 AND (c.cooldown_until IS NULL OR c.cooldown_until <= ?)
               ORDER BY c.next_follow_up ASC NULLS LAST
               LIMIT 20""",
            (today, today, today),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def get_crm_stats(db_path: Path | None = None) -> dict:
    """CRM stats for dashboard."""
    conn = _get_conn(db_path)
    try:
        init_crm_db(db_path)
        total_contacts = conn.execute("SELECT COUNT(*) AS c FROM contacts").fetchone()["c"]
        active_contacts = conn.execute(
            "SELECT COUNT(*) AS c FROM contacts WHERE status = 'active'"
        ).fetchone()["c"]
        total_convs = conn.execute(
            "SELECT COUNT(*) AS c FROM conversations WHERE is_active = 1"
        ).fetchone()["c"]
        replied = conn.execute(
            "SELECT COUNT(*) AS c FROM conversations WHERE stage = 'replied'"
        ).fetchone()["c"]
        follow_ups_due = conn.execute(
            """SELECT COUNT(*) AS c FROM conversations c
               JOIN contacts ct ON c.contact_id = ct.id
               WHERE c.is_active = 1
                 AND c.stage NOT IN ('replied', 'dead', 'closed')
                 AND ct.status = 'active'
                 AND (c.next_follow_up <= ? OR c.next_follow_up IS NULL)""",
            (datetime.utcnow().date().isoformat(),),
        ).fetchone()["c"]
        total_touchpoints = conn.execute("SELECT COUNT(*) AS c FROM touchpoints").fetchone()["c"]

        return {
            "total_contacts": total_contacts,
            "active_contacts": active_contacts,
            "total_conversations": total_convs,
            "replied_count": replied,
            "reply_rate": replied / max(total_convs, 1),
            "follow_ups_due": follow_ups_due,
            "total_touchpoints": total_touchpoints,
        }
    finally:
        conn.close()
