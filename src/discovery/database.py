"""SQLite database for discovered jobs.

Stores thousands of job postings with structured metadata for
LinkedIn-level filtering (role category, experience level, job type, skills).
Google Sheets can't handle this volume — SQLite is local, fast, and free.

Schema:
- discovered_jobs: main table with all extracted fields
- Indexes on: category, experience_level, job_type, company, score
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.config import PROJECT_ROOT
from src.utils.logging import get_logger

logger = get_logger(__name__)

DB_PATH = PROJECT_ROOT / "data" / "discovered_jobs.db"


def get_db() -> sqlite3.Connection:
    """Get a SQLite connection with row factory."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent access
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create tables and indexes if they don't exist."""
    conn = get_db()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS discovered_jobs (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                company TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                location TEXT DEFAULT '',
                source_name TEXT DEFAULT '',

                -- ML-extracted structured fields
                category TEXT DEFAULT '',          -- backend, frontend, data_science, ml, devops, etc.
                experience_level TEXT DEFAULT '',   -- entry, mid, senior, lead, staff, principal
                experience_years_min INTEGER DEFAULT 0,
                experience_years_max INTEGER DEFAULT 0,
                job_type TEXT DEFAULT '',           -- full_time, part_time, contract, internship
                remote_type TEXT DEFAULT '',        -- remote, hybrid, onsite
                salary_min INTEGER DEFAULT 0,
                salary_max INTEGER DEFAULT 0,
                salary_currency TEXT DEFAULT 'USD',
                skills TEXT DEFAULT '',             -- comma-separated: python,sql,aws
                education TEXT DEFAULT '',          -- bachelors, masters, phd, none

                -- Scoring and status
                match_score REAL DEFAULT 0.0,
                status TEXT DEFAULT 'new',          -- new, saved, applied, dismissed
                parsed INTEGER DEFAULT 0,           -- 1 if ML parsing is done
                tracked INTEGER DEFAULT 0,          -- 1 if pushed to main tracker (Google Sheets)

                -- Timestamps
                discovered_at TEXT NOT NULL,
                parsed_at TEXT DEFAULT '',
                updated_at TEXT DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_category ON discovered_jobs(category);
            CREATE INDEX IF NOT EXISTS idx_experience_level ON discovered_jobs(experience_level);
            CREATE INDEX IF NOT EXISTS idx_job_type ON discovered_jobs(job_type);
            CREATE INDEX IF NOT EXISTS idx_company ON discovered_jobs(company);
            CREATE INDEX IF NOT EXISTS idx_match_score ON discovered_jobs(match_score);
            CREATE INDEX IF NOT EXISTS idx_status ON discovered_jobs(status);
            CREATE INDEX IF NOT EXISTS idx_discovered_at ON discovered_jobs(discovered_at);
            CREATE INDEX IF NOT EXISTS idx_remote_type ON discovered_jobs(remote_type);
        """)
        conn.commit()
        logger.info("Discovery database initialized")
    finally:
        conn.close()


def insert_job(job: dict) -> str | None:
    """Insert a discovered job. Returns ID or None if duplicate URL."""
    conn = get_db()
    try:
        job_id = str(uuid.uuid4())[:8]
        conn.execute(
            """INSERT INTO discovered_jobs
               (id, title, company, url, description, location, source_name,
                match_score, discovered_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                job.get("title", ""),
                job.get("company", ""),
                job.get("url", ""),
                job.get("description", "")[:5000],
                job.get("location", ""),
                job.get("source_name", ""),
                job.get("score", 0.0),
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        return job_id
    except sqlite3.IntegrityError:
        # Duplicate URL
        return None
    finally:
        conn.close()


def update_parsed_fields(job_id: str, fields: dict) -> None:
    """Update ML-extracted fields after parsing."""
    conn = get_db()
    try:
        conn.execute(
            """UPDATE discovered_jobs SET
               category=?, experience_level=?, experience_years_min=?, experience_years_max=?,
               job_type=?, remote_type=?, salary_min=?, salary_max=?, salary_currency=?,
               skills=?, education=?, parsed=1, parsed_at=?, updated_at=?
               WHERE id=?""",
            (
                fields.get("category", ""),
                fields.get("experience_level", ""),
                fields.get("experience_years_min", 0),
                fields.get("experience_years_max", 0),
                fields.get("job_type", "full_time"),
                fields.get("remote_type", ""),
                fields.get("salary_min", 0),
                fields.get("salary_max", 0),
                fields.get("salary_currency", "USD"),
                fields.get("skills", ""),
                fields.get("education", ""),
                datetime.now().isoformat(),
                datetime.now().isoformat(),
                job_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def update_status(job_id: str, status: str) -> None:
    """Update job status (new, saved, applied, dismissed)."""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE discovered_jobs SET status=?, updated_at=? WHERE id=?",
            (status, datetime.now().isoformat(), job_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_unparsed_jobs(limit: int = 50) -> list[dict]:
    """Get jobs that haven't been ML-parsed yet."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM discovered_jobs WHERE parsed=0 ORDER BY discovered_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def search_jobs(
    category: str = "",
    experience_level: str = "",
    experience_years_min: int = 0,
    experience_years_max: int = 99,
    job_type: str = "",
    remote_type: str = "",
    keyword: str = "",
    company: str = "",
    status: str = "",
    min_score: float = 0.0,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Search discovered jobs with LinkedIn-level filtering.

    Returns (jobs, total_count).
    """
    conn = get_db()
    try:
        conditions = []
        params = []

        if category:
            conditions.append("category = ?")
            params.append(category)

        if experience_level:
            conditions.append("experience_level = ?")
            params.append(experience_level)

        if experience_years_min > 0:
            conditions.append("experience_years_max >= ?")
            params.append(experience_years_min)

        if experience_years_max < 99:
            conditions.append("experience_years_min <= ?")
            params.append(experience_years_max)

        if job_type:
            conditions.append("job_type = ?")
            params.append(job_type)

        if remote_type:
            conditions.append("remote_type = ?")
            params.append(remote_type)

        if keyword:
            conditions.append("(title LIKE ? OR description LIKE ? OR skills LIKE ?)")
            kw = f"%{keyword}%"
            params.extend([kw, kw, kw])

        if company:
            conditions.append("company LIKE ?")
            params.append(f"%{company}%")

        if status:
            conditions.append("status = ?")
            params.append(status)

        if min_score > 0:
            conditions.append("match_score >= ?")
            params.append(min_score)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        # Get total count
        count_row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM discovered_jobs {where}", params
        ).fetchone()
        total = count_row["cnt"] if count_row else 0

        # Get paginated results
        rows = conn.execute(
            f"""SELECT * FROM discovered_jobs {where}
                ORDER BY match_score DESC, discovered_at DESC
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()

        return [dict(r) for r in rows], total
    finally:
        conn.close()


def get_stats() -> dict:
    """Get summary statistics for the discovery database."""
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) as cnt FROM discovered_jobs").fetchone()["cnt"]
        parsed = conn.execute("SELECT COUNT(*) as cnt FROM discovered_jobs WHERE parsed=1").fetchone()["cnt"]
        by_category = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM discovered_jobs WHERE category != '' GROUP BY category ORDER BY cnt DESC"
        ).fetchall()
        by_level = conn.execute(
            "SELECT experience_level, COUNT(*) as cnt FROM discovered_jobs WHERE experience_level != '' GROUP BY experience_level ORDER BY cnt DESC"
        ).fetchall()
        by_type = conn.execute(
            "SELECT job_type, COUNT(*) as cnt FROM discovered_jobs WHERE job_type != '' GROUP BY job_type ORDER BY cnt DESC"
        ).fetchall()
        by_status = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM discovered_jobs GROUP BY status ORDER BY cnt DESC"
        ).fetchall()

        return {
            "total": total,
            "parsed": parsed,
            "unparsed": total - parsed,
            "by_category": {r["category"]: r["cnt"] for r in by_category},
            "by_level": {r["experience_level"]: r["cnt"] for r in by_level},
            "by_type": {r["job_type"]: r["cnt"] for r in by_type},
            "by_status": {r["status"]: r["cnt"] for r in by_status},
        }
    finally:
        conn.close()


def get_all_urls() -> set[str]:
    """Get all discovered job URLs for deduplication."""
    conn = get_db()
    try:
        rows = conn.execute("SELECT url FROM discovered_jobs").fetchall()
        return {r["url"] for r in rows}
    finally:
        conn.close()
