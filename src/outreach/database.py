"""Outreach database — sequences, drafts, variants.

Schema:
  outreach_sequences  — one row per contact being worked through a sequence
  outreach_drafts     — drafts pending human approval
  outreach_variants   — A/B variant performance stats
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from src.utils.logging import get_logger

logger = get_logger(__name__)

OUTREACH_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "outreach.db"

SEQUENCE_STAGES = ["initial", "follow_up_1", "follow_up_2"]
STAGE_DELAYS_DAYS = {"initial": 0, "follow_up_1": 3, "follow_up_2": 7}
FINAL_STAGE = "follow_up_2"
COLD_AFTER_DAYS = 14  # mark cold if no reply within 14d of last touch

DRAFT_STATUSES = frozenset(("pending", "approved", "rejected", "sent", "skipped"))
SEQUENCE_STATUSES = frozenset(("active", "replied", "cold", "paused", "completed"))


def _get_conn(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or OUTREACH_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _migrate_outreach_columns(conn: sqlite3.Connection) -> None:
    """Future-proof: add new columns without breaking existing DBs."""
    pass  # Nothing to migrate on first run


def init_outreach_db(db_path: Path | None = None) -> None:
    """Initialize outreach schema. Idempotent."""
    conn = _get_conn(db_path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS outreach_sequences (
                id TEXT PRIMARY KEY,
                contact_id TEXT NOT NULL,
                contact_email TEXT NOT NULL,
                contact_name TEXT DEFAULT '',
                company TEXT DEFAULT '',
                job_title TEXT DEFAULT '',
                current_stage TEXT DEFAULT 'initial',
                status TEXT DEFAULT 'active',
                next_due_at TEXT DEFAULT NULL,
                last_sent_at TEXT DEFAULT NULL,
                reply_received INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS outreach_drafts (
                id TEXT PRIMARY KEY,
                sequence_id TEXT NOT NULL,
                contact_id TEXT NOT NULL,
                contact_email TEXT NOT NULL,
                contact_name TEXT DEFAULT '',
                company TEXT DEFAULT '',
                stage TEXT NOT NULL,
                subject TEXT DEFAULT '',
                body TEXT NOT NULL,
                variant_id TEXT DEFAULT 'A',
                status TEXT DEFAULT 'pending',
                drafted_by TEXT DEFAULT 'template',
                draft_notes TEXT DEFAULT '',
                approved_at TEXT DEFAULT NULL,
                sent_at TEXT DEFAULT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (sequence_id) REFERENCES outreach_sequences(id)
            );

            CREATE TABLE IF NOT EXISTS outreach_variants (
                id TEXT PRIMARY KEY,
                stage TEXT NOT NULL,
                variant_label TEXT NOT NULL,
                template_name TEXT DEFAULT '',
                sends INTEGER DEFAULT 0,
                replies INTEGER DEFAULT 0,
                reply_rate REAL DEFAULT 0.0,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_seq_contact   ON outreach_sequences(contact_id);
            CREATE INDEX IF NOT EXISTS idx_seq_status    ON outreach_sequences(status);
            CREATE INDEX IF NOT EXISTS idx_seq_due       ON outreach_sequences(next_due_at);
            CREATE INDEX IF NOT EXISTS idx_drafts_status ON outreach_drafts(status);
            CREATE INDEX IF NOT EXISTS idx_drafts_seq    ON outreach_drafts(sequence_id);
        """)
        _migrate_outreach_columns(conn)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Sequences
# ---------------------------------------------------------------------------

def start_sequence(
    contact_id: str,
    contact_email: str,
    contact_name: str = "",
    company: str = "",
    job_title: str = "",
    db_path: Path | None = None,
) -> dict:
    """Start a new outreach sequence for a contact."""
    init_outreach_db(db_path)
    conn = _get_conn(db_path)
    try:
        # Check if active sequence already exists for this contact
        existing = conn.execute(
            "SELECT * FROM outreach_sequences WHERE contact_id = ? AND status = 'active'",
            (contact_id,)
        ).fetchone()
        if existing:
            return dict(existing)

        now = datetime.utcnow().isoformat()
        seq_id = str(uuid.uuid4())[:8]
        conn.execute(
            """INSERT INTO outreach_sequences
               (id, contact_id, contact_email, contact_name, company, job_title,
                current_stage, status, next_due_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'initial', 'active', ?, ?, ?)""",
            (seq_id, contact_id, contact_email, contact_name, company, job_title,
             now, now, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM outreach_sequences WHERE id = ?", (seq_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def get_sequence(seq_id: str, db_path: Path | None = None) -> dict | None:
    init_outreach_db(db_path)
    conn = _get_conn(db_path)
    try:
        row = conn.execute("SELECT * FROM outreach_sequences WHERE id = ?", (seq_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_due_sequences(db_path: Path | None = None) -> list[dict]:
    """Return active sequences where next_due_at <= now (ready for next draft)."""
    init_outreach_db(db_path)
    conn = _get_conn(db_path)
    try:
        now = datetime.utcnow().isoformat()
        rows = conn.execute(
            """SELECT * FROM outreach_sequences
               WHERE status = 'active' AND next_due_at <= ?
               ORDER BY next_due_at ASC""",
            (now,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def advance_sequence(seq_id: str, db_path: Path | None = None) -> dict | None:
    """Advance sequence to next stage and set next_due_at. Returns updated seq or None if at end."""
    conn = _get_conn(db_path)
    try:
        seq = conn.execute("SELECT * FROM outreach_sequences WHERE id = ?", (seq_id,)).fetchone()
        if not seq:
            return None
        seq = dict(seq)
        now = datetime.utcnow()

        current = seq["current_stage"]
        idx = SEQUENCE_STAGES.index(current) if current in SEQUENCE_STAGES else -1
        if idx < len(SEQUENCE_STAGES) - 1:
            next_stage = SEQUENCE_STAGES[idx + 1]
            delay = STAGE_DELAYS_DAYS.get(next_stage, 3)
            next_due = (now + timedelta(days=delay)).isoformat()
            conn.execute(
                """UPDATE outreach_sequences SET current_stage = ?, next_due_at = ?,
                   last_sent_at = ?, updated_at = ? WHERE id = ?""",
                (next_stage, next_due, now.isoformat(), now.isoformat(), seq_id),
            )
        else:
            # Completed all stages
            conn.execute(
                """UPDATE outreach_sequences SET status = 'completed',
                   last_sent_at = ?, updated_at = ? WHERE id = ?""",
                (now.isoformat(), now.isoformat(), seq_id),
            )
        conn.commit()
        row = conn.execute("SELECT * FROM outreach_sequences WHERE id = ?", (seq_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def mark_sequence_replied(seq_id: str, db_path: Path | None = None) -> None:
    conn = _get_conn(db_path)
    try:
        now = datetime.utcnow().isoformat()
        conn.execute(
            "UPDATE outreach_sequences SET status = 'replied', reply_received = 1, updated_at = ? WHERE id = ?",
            (now, seq_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_cold_sequences(db_path: Path | None = None) -> int:
    """Mark sequences as cold if last_sent_at > COLD_AFTER_DAYS and no reply."""
    conn = _get_conn(db_path)
    try:
        cutoff = (datetime.utcnow() - timedelta(days=COLD_AFTER_DAYS)).isoformat()
        now = datetime.utcnow().isoformat()
        result = conn.execute(
            """UPDATE outreach_sequences SET status = 'cold', updated_at = ?
               WHERE status = 'active' AND reply_received = 0
               AND last_sent_at IS NOT NULL AND last_sent_at < ?""",
            (now, cutoff),
        )
        conn.commit()
        return result.rowcount
    finally:
        conn.close()


def list_sequences(
    status: str | None = None,
    limit: int = 50,
    db_path: Path | None = None,
) -> list[dict]:
    init_outreach_db(db_path)
    conn = _get_conn(db_path)
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM outreach_sequences WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM outreach_sequences ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------

def save_draft(
    sequence_id: str,
    contact_id: str,
    contact_email: str,
    stage: str,
    subject: str,
    body: str,
    contact_name: str = "",
    company: str = "",
    variant_id: str = "A",
    drafted_by: str = "template",
    db_path: Path | None = None,
) -> dict:
    init_outreach_db(db_path)
    conn = _get_conn(db_path)
    try:
        now = datetime.utcnow().isoformat()
        draft_id = str(uuid.uuid4())[:8]
        conn.execute(
            """INSERT INTO outreach_drafts
               (id, sequence_id, contact_id, contact_email, contact_name, company,
                stage, subject, body, variant_id, status, drafted_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (draft_id, sequence_id, contact_id, contact_email, contact_name, company,
             stage, subject, body[:2000], variant_id, drafted_by, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM outreach_drafts WHERE id = ?", (draft_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def get_draft(draft_id: str, db_path: Path | None = None) -> dict | None:
    init_outreach_db(db_path)
    conn = _get_conn(db_path)
    try:
        row = conn.execute("SELECT * FROM outreach_drafts WHERE id = ?", (draft_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_drafts(
    status: str = "pending",
    limit: int = 50,
    db_path: Path | None = None,
) -> list[dict]:
    init_outreach_db(db_path)
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM outreach_drafts WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def approve_draft(
    draft_id: str,
    db_path: Path | None = None,
) -> dict | None:
    conn = _get_conn(db_path)
    try:
        now = datetime.utcnow().isoformat()
        conn.execute(
            "UPDATE outreach_drafts SET status = 'approved', approved_at = ? WHERE id = ?",
            (now, draft_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM outreach_drafts WHERE id = ?", (draft_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def reject_draft(draft_id: str, notes: str = "", db_path: Path | None = None) -> None:
    conn = _get_conn(db_path)
    try:
        conn.execute(
            "UPDATE outreach_drafts SET status = 'rejected', draft_notes = ? WHERE id = ?",
            (notes, draft_id),
        )
        conn.commit()
    finally:
        conn.close()


def edit_draft(draft_id: str, subject: str | None = None, body: str | None = None, db_path: Path | None = None) -> dict | None:
    conn = _get_conn(db_path)
    try:
        if subject is not None:
            conn.execute("UPDATE outreach_drafts SET subject = ? WHERE id = ?", (subject, draft_id))
        if body is not None:
            conn.execute("UPDATE outreach_drafts SET body = ? WHERE id = ?", (body[:2000], draft_id))
        conn.commit()
        row = conn.execute("SELECT * FROM outreach_drafts WHERE id = ?", (draft_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def mark_draft_sent(draft_id: str, db_path: Path | None = None) -> None:
    conn = _get_conn(db_path)
    try:
        now = datetime.utcnow().isoformat()
        conn.execute(
            "UPDATE outreach_drafts SET status = 'sent', sent_at = ? WHERE id = ?",
            (now, draft_id),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# A/B Variants
# ---------------------------------------------------------------------------

def record_variant_send(variant_id: str, stage: str, template_name: str = "", db_path: Path | None = None) -> None:
    init_outreach_db(db_path)
    conn = _get_conn(db_path)
    try:
        now = datetime.utcnow().isoformat()
        existing = conn.execute(
            "SELECT * FROM outreach_variants WHERE variant_label = ? AND stage = ?",
            (variant_id, stage),
        ).fetchone()
        if existing:
            existing = dict(existing)
            sends = existing["sends"] + 1
            rate = existing["replies"] / sends if sends > 0 else 0.0
            conn.execute(
                "UPDATE outreach_variants SET sends = ?, reply_rate = ?, updated_at = ? WHERE id = ?",
                (sends, rate, now, existing["id"]),
            )
        else:
            vid = str(uuid.uuid4())[:8]
            conn.execute(
                """INSERT INTO outreach_variants
                   (id, stage, variant_label, template_name, sends, replies, reply_rate, updated_at)
                   VALUES (?, ?, ?, ?, 1, 0, 0.0, ?)""",
                (vid, stage, variant_id, template_name, now),
            )
        conn.commit()
    finally:
        conn.close()


def record_variant_reply(variant_id: str, stage: str, db_path: Path | None = None) -> None:
    conn = _get_conn(db_path)
    try:
        now = datetime.utcnow().isoformat()
        existing = conn.execute(
            "SELECT * FROM outreach_variants WHERE variant_label = ? AND stage = ?",
            (variant_id, stage),
        ).fetchone()
        if existing:
            existing = dict(existing)
            replies = existing["replies"] + 1
            sends = existing["sends"]
            rate = replies / sends if sends > 0 else 0.0
            conn.execute(
                "UPDATE outreach_variants SET replies = ?, reply_rate = ?, updated_at = ? WHERE id = ?",
                (replies, rate, now, existing["id"]),
            )
            conn.commit()
    finally:
        conn.close()


def get_best_variant(stage: str, db_path: Path | None = None) -> str:
    """UCB1-style: return variant with best reply_rate (min 3 sends), else A."""
    init_outreach_db(db_path)
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM outreach_variants WHERE stage = ? AND sends >= 3 ORDER BY reply_rate DESC",
            (stage,),
        ).fetchall()
        if rows:
            return dict(rows[0])["variant_label"]
        return "A"
    finally:
        conn.close()


def get_variant_stats(db_path: Path | None = None) -> list[dict]:
    init_outreach_db(db_path)
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM outreach_variants ORDER BY stage, reply_rate DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def get_outreach_stats(db_path: Path | None = None) -> dict:
    init_outreach_db(db_path)
    conn = _get_conn(db_path)
    try:
        total_seqs = conn.execute("SELECT COUNT(*) AS c FROM outreach_sequences").fetchone()["c"]
        active = conn.execute("SELECT COUNT(*) AS c FROM outreach_sequences WHERE status = 'active'").fetchone()["c"]
        replied = conn.execute("SELECT COUNT(*) AS c FROM outreach_sequences WHERE status = 'replied'").fetchone()["c"]
        cold = conn.execute("SELECT COUNT(*) AS c FROM outreach_sequences WHERE status = 'cold'").fetchone()["c"]
        pending_drafts = conn.execute("SELECT COUNT(*) AS c FROM outreach_drafts WHERE status = 'pending'").fetchone()["c"]
        sent_today_cutoff = datetime.utcnow().replace(hour=0, minute=0, second=0).isoformat()
        sent_today = conn.execute(
            "SELECT COUNT(*) AS c FROM outreach_drafts WHERE status = 'sent' AND sent_at >= ?",
            (sent_today_cutoff,),
        ).fetchone()["c"]
        reply_rate = round(replied / total_seqs, 3) if total_seqs > 0 else 0.0
        return {
            "total_sequences": total_seqs,
            "active_sequences": active,
            "replied": replied,
            "cold": cold,
            "pending_drafts": pending_drafts,
            "sent_today": sent_today,
            "reply_rate": reply_rate,
        }
    finally:
        conn.close()
