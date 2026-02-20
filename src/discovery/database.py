"""SQLite database for discovered jobs.

Robust database with:
- discovered_jobs: main table with 25+ structured fields
- discovery_sources: per-source tracking (last fetch, error count, ETag cache)
- companies: normalized company registry for canonical dedup
- Indexes on all filter columns for fast queries
- Fingerprint-based dedup (hash of normalized title+company+location)
- Company name normalization for cross-source matching

Design follows the 3-layer architecture:
- Layer A: Aggregator feeds (Indeed, RemoteOK, We Work Remotely, etc.)
- Layer B: ATS endpoints (Greenhouse, Lever, Ashby career feeds)
- Layer C: Long-tail RSS feeds (BuiltIn, company career pages)
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.config import PROJECT_ROOT
from src.utils.logging import get_logger

logger = get_logger(__name__)

DB_PATH = PROJECT_ROOT / "data" / "discovered_jobs.db"


# ---------------------------------------------------------------------------
# Company name normalization for cross-source dedup
# ---------------------------------------------------------------------------

# Common suffixes to strip for normalization
_COMPANY_SUFFIXES = re.compile(
    r"\s*\b(inc|llc|ltd|corp|corporation|co|company|group|holdings|"
    r"technologies|tech|labs|software|solutions|services|international|"
    r"global|gmbh|ag|plc|sa|pty)\b\.?$",
    re.IGNORECASE,
)

# Known aliases: map variant names to canonical form
_COMPANY_ALIASES = {
    "meta platforms": "meta",
    "facebook": "meta",
    "alphabet": "google",
    "microsoft corporation": "microsoft",
    "amazon.com": "amazon",
    "amazon web services": "aws",
    "aws": "aws",
    "apple inc": "apple",
    "ibm corporation": "ibm",
}


def normalize_company(name: str) -> str:
    """Normalize a company name for dedup matching.

    Strips suffixes (Inc, LLC, etc.), lowercases, resolves known aliases.
    """
    if not name:
        return ""
    cleaned = name.strip().lower()
    # Check aliases first
    if cleaned in _COMPANY_ALIASES:
        return _COMPANY_ALIASES[cleaned]
    # Strip common suffixes
    cleaned = _COMPANY_SUFFIXES.sub("", cleaned).strip()
    # Remove trailing punctuation
    cleaned = cleaned.rstrip(".,- ")
    return cleaned or name.lower().strip()


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
        # Step 1: Create tables
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
                category TEXT DEFAULT '',
                experience_level TEXT DEFAULT '',
                experience_years_min INTEGER DEFAULT 0,
                experience_years_max INTEGER DEFAULT 0,
                job_type TEXT DEFAULT '',
                remote_type TEXT DEFAULT '',
                salary_min INTEGER DEFAULT 0,
                salary_max INTEGER DEFAULT 0,
                salary_currency TEXT DEFAULT 'USD',
                skills TEXT DEFAULT '',
                education TEXT DEFAULT '',

                -- Dedup fingerprint (hash of normalized title+company+location)
                fingerprint TEXT DEFAULT '',

                -- Scoring and status
                match_score REAL DEFAULT 0.0,
                status TEXT DEFAULT 'new',
                parsed INTEGER DEFAULT 0,
                tracked INTEGER DEFAULT 0,
                applied_at TEXT DEFAULT '',

                -- Timestamps
                discovered_at TEXT NOT NULL,
                parsed_at TEXT DEFAULT '',
                updated_at TEXT DEFAULT ''
            );

            -- Source tracking table with ETag caching and scheduling
            CREATE TABLE IF NOT EXISTS discovery_sources (
                source_name TEXT PRIMARY KEY,
                source_type TEXT DEFAULT '',       -- rss, api, career_rss
                layer TEXT DEFAULT 'B',            -- A=aggregator, B=ATS, C=long-tail
                base_url TEXT DEFAULT '',
                last_fetched_at TEXT DEFAULT '',
                last_job_count INTEGER DEFAULT 0,
                total_jobs_found INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0,
                consecutive_errors INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 1,
                -- HTTP caching for efficient re-fetching
                etag TEXT DEFAULT '',
                last_modified TEXT DEFAULT '',
                content_hash TEXT DEFAULT '',       -- hash of last response for change detection
                -- Scheduling policy
                fetch_interval_minutes INTEGER DEFAULT 120
            );

            -- Company registry for canonical dedup
            CREATE TABLE IF NOT EXISTS companies (
                company_id TEXT PRIMARY KEY,
                name_raw TEXT DEFAULT '',
                name_normalized TEXT DEFAULT '' UNIQUE,
                domain TEXT DEFAULT '',
                ats_type TEXT DEFAULT '',          -- greenhouse, lever, ashby, workday, etc.
                career_url TEXT DEFAULT '',
                job_count INTEGER DEFAULT 0,
                first_seen TEXT DEFAULT '',
                last_seen TEXT DEFAULT ''
            );
        """)

        # Step 2: Migrate columns for existing DBs (BEFORE index creation)
        _migrate_columns(conn)

        # Step 3: Create indexes (after columns exist)
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_category ON discovered_jobs(category);
            CREATE INDEX IF NOT EXISTS idx_experience_level ON discovered_jobs(experience_level);
            CREATE INDEX IF NOT EXISTS idx_job_type ON discovered_jobs(job_type);
            CREATE INDEX IF NOT EXISTS idx_company ON discovered_jobs(company);
            CREATE INDEX IF NOT EXISTS idx_match_score ON discovered_jobs(match_score);
            CREATE INDEX IF NOT EXISTS idx_status ON discovered_jobs(status);
            CREATE INDEX IF NOT EXISTS idx_discovered_at ON discovered_jobs(discovered_at);
            CREATE INDEX IF NOT EXISTS idx_remote_type ON discovered_jobs(remote_type);
            CREATE INDEX IF NOT EXISTS idx_fingerprint ON discovered_jobs(fingerprint);
        """)

        conn.commit()
        logger.info("Discovery database initialized")
    finally:
        conn.close()


def _migrate_columns(conn: sqlite3.Connection) -> None:
    """Add columns that may not exist in older DB versions."""
    # discovered_jobs migrations
    existing = {row[1] for row in conn.execute("PRAGMA table_info(discovered_jobs)").fetchall()}
    job_migrations = [
        ("fingerprint", "TEXT DEFAULT ''"),
        ("applied_at", "TEXT DEFAULT ''"),
    ]
    for col_name, col_type in job_migrations:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE discovered_jobs ADD COLUMN {col_name} {col_type}")

    # discovery_sources migrations
    try:
        src_cols = {row[1] for row in conn.execute("PRAGMA table_info(discovery_sources)").fetchall()}
        src_migrations = [
            ("layer", "TEXT DEFAULT 'B'"),
            ("etag", "TEXT DEFAULT ''"),
            ("last_modified", "TEXT DEFAULT ''"),
            ("content_hash", "TEXT DEFAULT ''"),
            ("fetch_interval_minutes", "INTEGER DEFAULT 120"),
            ("consecutive_errors", "INTEGER DEFAULT 0"),
        ]
        for col_name, col_type in src_migrations:
            if col_name not in src_cols:
                conn.execute(f"ALTER TABLE discovery_sources ADD COLUMN {col_name} {col_type}")
    except Exception:
        pass  # Table might not exist yet


def _compute_fingerprint(title: str, company: str, location: str) -> str:
    """Compute a dedup fingerprint from normalized fields.

    Uses company normalization for cross-source matching.
    """
    norm_company = normalize_company(company)
    normalized = f"{title.lower().strip()}|{norm_company}|{location.lower().strip()}"
    return hashlib.md5(normalized.encode()).hexdigest()[:16]


def _register_company(conn: sqlite3.Connection, company: str, source_name: str) -> None:
    """Register or update a company in the company registry."""
    if not company:
        return
    norm = normalize_company(company)
    now = datetime.now().isoformat()
    # Detect ATS type from source name
    ats_type = ""
    src_lower = source_name.lower()
    if "greenhouse" in src_lower or "(GH)" in source_name:
        ats_type = "greenhouse"
    elif "lever" in src_lower:
        ats_type = "lever"
    elif "ashby" in src_lower:
        ats_type = "ashby"

    try:
        conn.execute(
            """INSERT INTO companies (company_id, name_raw, name_normalized, ats_type, first_seen, last_seen, job_count)
               VALUES (?, ?, ?, ?, ?, ?, 1)
               ON CONFLICT(name_normalized) DO UPDATE SET
                   last_seen=excluded.last_seen,
                   job_count=job_count + 1""",
            (str(uuid.uuid4())[:8], company, norm, ats_type, now, now),
        )
    except Exception:
        pass  # Best-effort company tracking


def insert_job(job: dict) -> str | None:
    """Insert a discovered job. Returns ID or None if duplicate URL."""
    conn = get_db()
    try:
        job_id = str(uuid.uuid4())[:8]
        fp = _compute_fingerprint(
            job.get("title", ""), job.get("company", ""), job.get("location", ""),
        )
        conn.execute(
            """INSERT INTO discovered_jobs
               (id, title, company, url, description, location, source_name,
                match_score, fingerprint, discovered_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                job.get("title", ""),
                job.get("company", ""),
                job.get("url", ""),
                job.get("description", "")[:5000],
                job.get("location", ""),
                job.get("source_name", ""),
                job.get("score", 0.0),
                fp,
                datetime.now().isoformat(),
            ),
        )
        # Register company in the registry
        _register_company(conn, job.get("company", ""), job.get("source_name", ""))
        conn.commit()
        return job_id
    except sqlite3.IntegrityError:
        # Duplicate URL
        return None
    finally:
        conn.close()


def get_job_by_id(job_id: str) -> dict | None:
    """Get a single job by ID with all fields."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM discovered_jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def mark_applied(job_id: str) -> None:
    """Mark a job as applied with timestamp."""
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE discovered_jobs SET status='applied', applied_at=?, updated_at=? WHERE id=?",
            (now, now, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_tracked(job_id: str) -> None:
    """Mark a job as pushed to the main tracker (Google Sheets)."""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE discovered_jobs SET tracked=1, updated_at=? WHERE id=?",
            (datetime.now().isoformat(), job_id),
        )
        conn.commit()
    finally:
        conn.close()


def update_source_stats(source_name: str, source_type: str, base_url: str,
                        job_count: int, error: bool = False,
                        etag: str = "", last_modified: str = "",
                        content_hash: str = "", layer: str = "B") -> None:
    """Track per-source fetch statistics with ETag caching."""
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO discovery_sources (source_name, source_type, base_url, layer,
                   last_fetched_at, last_job_count, total_jobs_found, error_count,
                   consecutive_errors, etag, last_modified, content_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(source_name) DO UPDATE SET
                   last_fetched_at=excluded.last_fetched_at,
                   last_job_count=excluded.last_job_count,
                   total_jobs_found=total_jobs_found + excluded.total_jobs_found,
                   error_count=error_count + excluded.error_count,
                   consecutive_errors=CASE WHEN excluded.error_count > 0
                       THEN consecutive_errors + 1 ELSE 0 END,
                   etag=CASE WHEN excluded.etag != '' THEN excluded.etag ELSE etag END,
                   last_modified=CASE WHEN excluded.last_modified != '' THEN excluded.last_modified ELSE last_modified END,
                   content_hash=CASE WHEN excluded.content_hash != '' THEN excluded.content_hash ELSE content_hash END""",
            (
                source_name, source_type, base_url, layer,
                datetime.now().isoformat(),
                job_count, job_count,
                1 if error else 0,
                1 if error else 0,
                etag, last_modified, content_hash,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_source_cache(source_name: str) -> dict:
    """Get cached ETag/Last-Modified for a source (for conditional requests)."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT etag, last_modified, content_hash FROM discovery_sources WHERE source_name=?",
            (source_name,),
        ).fetchone()
        if row:
            return {"etag": row["etag"], "last_modified": row["last_modified"],
                    "content_hash": row["content_hash"]}
        return {"etag": "", "last_modified": "", "content_hash": ""}
    except Exception:
        return {"etag": "", "last_modified": "", "content_hash": ""}
    finally:
        conn.close()


def get_companies(limit: int = 100) -> list[dict]:
    """Get the company registry sorted by job count."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM companies ORDER BY job_count DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def get_all_fingerprints() -> set[str]:
    """Get all fingerprints for cross-source dedup."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT fingerprint FROM discovered_jobs WHERE fingerprint != ''"
        ).fetchall()
        return {r["fingerprint"] for r in rows}
    except Exception:
        return set()
    finally:
        conn.close()


def get_source_stats() -> list[dict]:
    """Get per-source statistics."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM discovery_sources ORDER BY total_jobs_found DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
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


VALID_SORT_FIELDS = {
    "score": "match_score DESC",
    "newest": "discovered_at DESC",
    "oldest": "discovered_at ASC",
    "company": "company ASC",
    "title": "title ASC",
}


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
    sort_by: str = "score",
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Search discovered jobs with LinkedIn-level filtering.

    Args:
        sort_by: One of "score", "newest", "oldest", "company", "title".
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

        # Sort order
        order = VALID_SORT_FIELDS.get(sort_by, "match_score DESC")

        # Get paginated results
        rows = conn.execute(
            f"""SELECT * FROM discovered_jobs {where}
                ORDER BY {order}, discovered_at DESC
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
