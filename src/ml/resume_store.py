"""Resume storage — SQLite-backed store for uploaded resumes.

Each resume is stored with:
- Raw text
- Parsed structured JSON (from ResumeParser)
- Skill inventory
- Default flag (one resume can be the default)
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.config import PROJECT_ROOT

DB_PATH = PROJECT_ROOT / "data" / "resumes.db"


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_resume_db() -> None:
    """Create the resumes table if it doesn't exist."""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS resumes (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            parsed_json TEXT DEFAULT '{}',
            skill_inventory TEXT DEFAULT '[]',
            skill_categories TEXT DEFAULT '{}',
            total_bullets INTEGER DEFAULT 0,
            total_metrics INTEGER DEFAULT 0,
            is_default INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def save_resume(
    name: str,
    raw_text: str,
    parsed_json: dict | None = None,
    skill_inventory: list[str] | None = None,
    skill_categories: dict | None = None,
    total_bullets: int = 0,
    total_metrics: int = 0,
    is_default: bool = False,
) -> dict:
    """Save a new resume. Returns the created record."""
    init_resume_db()
    conn = _get_conn()

    resume_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc).isoformat()

    # If setting as default, unset all others first
    if is_default:
        conn.execute("UPDATE resumes SET is_default = 0")

    conn.execute(
        """INSERT INTO resumes
           (id, name, raw_text, parsed_json, skill_inventory, skill_categories,
            total_bullets, total_metrics, is_default, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            resume_id,
            name,
            raw_text,
            json.dumps(parsed_json or {}),
            json.dumps(skill_inventory or []),
            json.dumps(skill_categories or {}),
            total_bullets,
            total_metrics,
            1 if is_default else 0,
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()

    return get_resume(resume_id)


def get_resume(resume_id: str) -> Optional[dict]:
    """Get a single resume by ID."""
    init_resume_db()
    conn = _get_conn()
    row = conn.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_dict(row)


def list_resumes() -> list[dict]:
    """List all resumes (without raw_text for efficiency)."""
    init_resume_db()
    conn = _get_conn()
    rows = conn.execute(
        """SELECT id, name, skill_inventory, skill_categories,
                  total_bullets, total_metrics, is_default, created_at, updated_at
           FROM resumes ORDER BY is_default DESC, created_at DESC"""
    ).fetchall()
    conn.close()
    results = []
    for row in rows:
        d = dict(row)
        d["skill_inventory"] = json.loads(d.get("skill_inventory") or "[]")
        d["skill_categories"] = json.loads(d.get("skill_categories") or "{}")
        d["is_default"] = bool(d.get("is_default", 0))
        results.append(d)
    return results


def set_default_resume(resume_id: str) -> bool:
    """Set a resume as the default. Unsets all others."""
    init_resume_db()
    conn = _get_conn()
    conn.execute("UPDATE resumes SET is_default = 0")
    cursor = conn.execute(
        "UPDATE resumes SET is_default = 1, updated_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), resume_id),
    )
    conn.commit()
    conn.close()
    return cursor.rowcount > 0


def delete_resume(resume_id: str) -> bool:
    """Delete a resume by ID."""
    init_resume_db()
    conn = _get_conn()
    cursor = conn.execute("DELETE FROM resumes WHERE id = ?", (resume_id,))
    conn.commit()
    conn.close()
    return cursor.rowcount > 0


def get_default_resume() -> Optional[dict]:
    """Get the default resume, or the most recent one if no default is set."""
    init_resume_db()
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM resumes ORDER BY is_default DESC, created_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_dict(row)


def get_resume_count() -> int:
    """Get number of stored resumes."""
    init_resume_db()
    conn = _get_conn()
    count = conn.execute("SELECT COUNT(*) FROM resumes").fetchone()[0]
    conn.close()
    return count


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a DB row to a dict with parsed JSON fields."""
    d = dict(row)
    d["parsed_json"] = json.loads(d.get("parsed_json") or "{}")
    d["skill_inventory"] = json.loads(d.get("skill_inventory") or "[]")
    d["skill_categories"] = json.loads(d.get("skill_categories") or "{}")
    d["is_default"] = bool(d.get("is_default", 0))
    return d
