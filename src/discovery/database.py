"""SQLite database for discovered jobs.

Robust database with:
- discovered_jobs: main table with 30+ structured fields
- discovery_sources: per-source tracking (last fetch, error count, ETag cache)
- companies: normalized company registry for canonical dedup
- jobs_fts: FTS5 full-text search for blazing fast keyword queries
- Indexes on all filter columns for fast queries
- Fingerprint-based dedup (hash of normalized title+company+location)
- ATS job_id extraction from URLs for cross-source matching
- Company name normalization for cross-source matching
- Newness window tracking (first_seen, last_seen, posted_at)
- Adaptive scheduling (slow down dead sources, speed up productive ones)

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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

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


# ---------------------------------------------------------------------------
# ATS job_id extraction from URLs
# ---------------------------------------------------------------------------

_ATS_PATTERNS = [
    # Greenhouse: https://boards.greenhouse.io/company/jobs/12345
    re.compile(r"boards\.greenhouse\.io/\w+/jobs/(\d+)"),
    # Lever: https://jobs.lever.co/company/uuid
    re.compile(r"jobs\.lever\.co/\w+/([a-f0-9-]{36})"),
    # Ashby: https://jobs.ashbyhq.com/company/uuid
    re.compile(r"jobs\.ashbyhq\.com/[\w-]+/([a-f0-9-]{36})"),
]


def extract_ats_job_id(url: str) -> str:
    """Extract a unique ATS job ID from known URL patterns.

    Returns the ID if found, empty string otherwise.
    """
    if not url:
        return ""
    for pattern in _ATS_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return ""


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

                -- Dedup fields
                fingerprint TEXT DEFAULT '',         -- md5(normalized title+company+location)
                ats_job_id TEXT DEFAULT '',           -- extracted from ATS URL (Greenhouse/Lever/Ashby)

                -- Scoring and status
                match_score REAL DEFAULT 0.0,
                status TEXT DEFAULT 'new',
                parsed INTEGER DEFAULT 0,
                tracked INTEGER DEFAULT 0,
                applied_at TEXT DEFAULT '',

                -- Newness tracking
                first_seen_at TEXT NOT NULL,          -- when we first discovered this job
                last_seen_at TEXT DEFAULT '',          -- last time this URL appeared in a fetch
                posted_at TEXT DEFAULT '',             -- original posting date (from feed if available)

                -- Backfill flag — set 1 for historical records (no alert sent)
                is_backfill INTEGER DEFAULT 0,

                -- Full raw API response payload (JSON string) for re-normalization
                raw_payload_json TEXT DEFAULT '',

                -- Quality signals
                description_length INTEGER DEFAULT 0,
                is_staffing_agency INTEGER DEFAULT 0,  -- 1 = flagged as staffing/recruiting firm

                -- Source provenance — enables dashboard filtering by sender/website
                email_sender TEXT DEFAULT '',       -- raw sender email (e.g. jobseekers@email.ihire.com)
                source_domain TEXT DEFAULT '',      -- sender domain / source website (e.g. ihire.com)

                -- Alert tracking (idempotent Telegram notifications)
                alerted_at TEXT DEFAULT '',         -- ISO timestamp when Telegram alert sent, empty=not yet
                alert_status TEXT DEFAULT '',       -- 'sent', 'skipped_backfill', 'skipped_score'

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

            -- Cross-source job mapping (same job seen in multiple sources)
            CREATE TABLE IF NOT EXISTS jobs_source_map (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                primary_job_id TEXT NOT NULL,       -- ID in discovered_jobs (canonical record)
                duplicate_job_id TEXT,              -- ID of duplicate (if also stored)
                source_name TEXT NOT NULL,          -- source that found this duplicate
                source_url TEXT NOT NULL,           -- URL as seen in this source
                similarity_score REAL DEFAULT 1.0,  -- 1.0=exact, <1.0=soft match
                match_type TEXT DEFAULT 'url',      -- url, ats_id, fingerprint, embedding
                seen_at TEXT NOT NULL,
                UNIQUE(primary_job_id, source_name)
            );

            -- Async fetch queue: discovery finds URLs, workers fetch details
            -- Prevents long-running fetches from blocking the discovery loop
            CREATE TABLE IF NOT EXISTS job_fetch_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL,          -- api, ats, jsonld, gmail, rss
                fetch_key TEXT NOT NULL UNIQUE,     -- URL or job_id to fetch
                source_name TEXT DEFAULT '',        -- which source queued this
                status TEXT DEFAULT 'pending',      -- pending, running, done, error
                attempts INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 3,
                enqueued_at TEXT NOT NULL,
                started_at TEXT DEFAULT '',
                completed_at TEXT DEFAULT '',
                next_retry_at TEXT DEFAULT '',      -- backoff scheduling
                error_message TEXT DEFAULT '',
                result_job_id TEXT DEFAULT ''       -- ID in discovered_jobs once stored
            );

            -- Query grid tracking (per role+location query state)
            CREATE TABLE IF NOT EXISTS query_grid_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT NOT NULL,
                query_key TEXT NOT NULL,            -- role family keyword
                location_key TEXT NOT NULL,         -- location bucket
                last_fetched_at TEXT DEFAULT '',
                next_cursor TEXT DEFAULT '',        -- pagination cursor
                jobs_found_last_run INTEGER DEFAULT 0,
                total_jobs_found INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0,
                fetch_interval_minutes INTEGER DEFAULT 120,
                UNIQUE(source_name, query_key, location_key)
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
            CREATE INDEX IF NOT EXISTS idx_ats_job_id ON discovered_jobs(ats_job_id);
            CREATE INDEX IF NOT EXISTS idx_first_seen ON discovered_jobs(first_seen_at);
            CREATE INDEX IF NOT EXISTS idx_alerted_at ON discovered_jobs(alerted_at);
            CREATE INDEX IF NOT EXISTS idx_fetch_queue_status ON job_fetch_queue(status, next_retry_at);
        """)

        # Step 4: Create FTS5 full-text search index (if not exists)
        try:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5(
                    title, company, description, skills, location,
                    content='discovered_jobs',
                    content_rowid='rowid'
                )
            """)
        except Exception:
            pass  # FTS5 may not be available in all SQLite builds

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
        ("ats_job_id", "TEXT DEFAULT ''"),
        ("first_seen_at", "TEXT DEFAULT ''"),
        ("last_seen_at", "TEXT DEFAULT ''"),
        ("posted_at", "TEXT DEFAULT ''"),
        ("is_backfill", "INTEGER DEFAULT 0"),
        ("raw_payload_json", "TEXT DEFAULT ''"),
        ("description_length", "INTEGER DEFAULT 0"),
        ("is_staffing_agency", "INTEGER DEFAULT 0"),
        ("alerted_at", "TEXT DEFAULT ''"),
        ("alert_status", "TEXT DEFAULT ''"),
        ("email_sender", "TEXT DEFAULT ''"),
        ("source_domain", "TEXT DEFAULT ''"),
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
    """Insert a discovered job. Returns ID or None if duplicate URL.

    Extracts ATS job_id from URL, computes fingerprint, tracks newness.
    """
    conn = get_db()
    try:
        job_id = str(uuid.uuid4())[:8]
        fp = _compute_fingerprint(
            job.get("title", ""), job.get("company", ""), job.get("location", ""),
        )
        ats_id = extract_ats_job_id(job.get("url", ""))
        now = datetime.now().isoformat()
        posted = job.get("posted_at", "") or ""

        import json as _json
        desc = job.get("description", "")[:5000]
        raw_payload = job.get("raw_payload_json", "")
        if not raw_payload and "raw_payload" in job:
            try:
                raw_payload = _json.dumps(job["raw_payload"])[:10000]
            except Exception:
                raw_payload = ""

        # Derive source_domain from email_sender or source_name
        email_sender = job.get("email_sender", "")
        source_domain = job.get("source_domain", "")
        if not source_domain and email_sender and "@" in email_sender:
            source_domain = email_sender.split("@")[-1]
        if not source_domain:
            sn = job.get("source_name", "")
            if "Gmail:" in sn:
                source_domain = sn.replace("Gmail:", "").lower()
            elif ":" in sn:
                # e.g. "Greenhouse:OpenAI" → "greenhouse.io"
                prefix = sn.split(":")[0].lower()
                _ats_domains = {"greenhouse": "greenhouse.io", "lever": "lever.co",
                                "ashby": "ashbyhq.com", "workday": "myworkdayjobs.com"}
                source_domain = _ats_domains.get(prefix, prefix)

        conn.execute(
            """INSERT INTO discovered_jobs
               (id, title, company, url, description, location, source_name,
                match_score, fingerprint, ats_job_id, first_seen_at, last_seen_at,
                posted_at, discovered_at, is_backfill, raw_payload_json,
                description_length, is_staffing_agency, email_sender, source_domain)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                job.get("title", ""),
                job.get("company", ""),
                job.get("url", ""),
                desc,
                job.get("location", ""),
                job.get("source_name", ""),
                job.get("score", 0.0),
                fp, ats_id,
                now, now,
                posted, now,
                1 if job.get("is_backfill") else 0,
                raw_payload,
                len(desc),
                1 if job.get("is_staffing_agency") else 0,
                email_sender,
                source_domain,
            ),
        )
        # Register company in the registry
        _register_company(conn, job.get("company", ""), job.get("source_name", ""))
        conn.commit()
        return job_id
    except sqlite3.IntegrityError:
        # Duplicate URL — update last_seen_at instead
        try:
            conn.execute(
                "UPDATE discovered_jobs SET last_seen_at=? WHERE url=?",
                (datetime.now().isoformat(), job.get("url", "")),
            )
            conn.commit()
        except Exception:
            pass
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


def get_all_ats_ids() -> set[str]:
    """Get all ATS job IDs for cross-source dedup."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT ats_job_id FROM discovered_jobs WHERE ats_job_id != ''"
        ).fetchall()
        return {r["ats_job_id"] for r in rows}
    except Exception:
        return set()
    finally:
        conn.close()


def record_source_map(primary_job_id: str, source_name: str, source_url: str,
                      match_type: str = "fingerprint", similarity: float = 1.0) -> None:
    """Record a cross-source duplicate in jobs_source_map.

    Call this when a job is skipped as a duplicate so we track where else it appeared.
    """
    conn = get_db()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO jobs_source_map
               (primary_job_id, source_name, source_url, similarity_score, match_type, seen_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (primary_job_id, source_name, source_url, similarity, match_type,
             datetime.now().isoformat()),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Newness Window — only notify for truly new jobs
# ---------------------------------------------------------------------------

def get_new_jobs_since(hours: int = 2) -> list[dict]:
    """Get unalerted jobs first seen within the last N hours.

    Filters:
    - first_seen_at within the window (not stale)
    - is_backfill=0 (never alert for historical records)
    - alerted_at='' (not yet notified — idempotent)

    Use this for Telegram notifications.
    """
    conn = get_db()
    try:
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        rows = conn.execute(
            """SELECT * FROM discovered_jobs
               WHERE first_seen_at >= ?
                 AND is_backfill = 0
                 AND (alerted_at IS NULL OR alerted_at = '')
               ORDER BY match_score DESC, first_seen_at DESC""",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_alerted(job_id: str) -> None:
    """Mark a job as having been alerted via Telegram (idempotency guard)."""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE discovered_jobs SET alerted_at=?, alert_status='sent', updated_at=? WHERE id=?",
            (datetime.now().isoformat(), datetime.now().isoformat(), job_id),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def mark_alert_skipped(job_id: str, reason: str) -> None:
    """Mark a job as alert-skipped so we don't check it again."""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE discovered_jobs SET alerted_at=?, alert_status=?, updated_at=? WHERE id=?",
            (datetime.now().isoformat(), reason, datetime.now().isoformat(), job_id),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Job Fetch Queue — decouple discovery from detail fetching
# ---------------------------------------------------------------------------

def enqueue_fetch(fetch_key: str, source_type: str, source_name: str = "") -> bool:
    """Add a URL/job_id to the fetch queue.

    Returns True if newly enqueued, False if already in queue.
    """
    conn = get_db()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO job_fetch_queue
               (source_type, fetch_key, source_name, status, enqueued_at)
               VALUES (?, ?, ?, 'pending', ?)""",
            (source_type, fetch_key, source_name, datetime.now().isoformat()),
        )
        conn.commit()
        return conn.total_changes > 0
    except Exception:
        return False
    finally:
        conn.close()


def get_pending_queue(limit: int = 50) -> list[dict]:
    """Get pending fetch queue items ready to process (respects next_retry_at backoff)."""
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        rows = conn.execute(
            """SELECT * FROM job_fetch_queue
               WHERE status = 'pending'
                 AND attempts < max_attempts
                 AND (next_retry_at = '' OR next_retry_at <= ?)
               ORDER BY enqueued_at ASC
               LIMIT ?""",
            (now, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_queue_item(item_id: int, status: str,
                      error_message: str = "", result_job_id: str = "") -> None:
    """Update a fetch queue item's status."""
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        if status == "error":
            # Exponential backoff: 5min, 15min, 45min
            row = conn.execute(
                "SELECT attempts FROM job_fetch_queue WHERE id=?", (item_id,)
            ).fetchone()
            attempts = (row["attempts"] if row else 0) + 1
            backoff_minutes = 5 * (3 ** (attempts - 1))
            next_retry = (datetime.now() + timedelta(minutes=backoff_minutes)).isoformat()
            conn.execute(
                """UPDATE job_fetch_queue
                   SET status='pending', attempts=?, error_message=?, next_retry_at=?
                   WHERE id=?""",
                (attempts, error_message, next_retry, item_id),
            )
        elif status == "done":
            conn.execute(
                """UPDATE job_fetch_queue
                   SET status='done', completed_at=?, result_job_id=?, attempts=attempts+1
                   WHERE id=?""",
                (now, result_job_id, item_id),
            )
        elif status == "running":
            conn.execute(
                "UPDATE job_fetch_queue SET status='running', started_at=? WHERE id=?",
                (now, item_id),
            )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def get_queue_stats() -> dict:
    """Get fetch queue statistics."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM job_fetch_queue GROUP BY status"
        ).fetchall()
        return {r["status"]: r["cnt"] for r in rows}
    except Exception:
        return {}
    finally:
        conn.close()


def get_stale_jobs(days: int = 30) -> list[dict]:
    """Get jobs not seen in any feed for N days (likely closed/filled)."""
    conn = get_db()
    try:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        rows = conn.execute(
            """SELECT * FROM discovered_jobs
               WHERE last_seen_at != '' AND last_seen_at < ?
               AND status = 'new'
               ORDER BY last_seen_at ASC LIMIT 100""",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Adaptive Scheduling
# ---------------------------------------------------------------------------

def get_adaptive_interval(source_name: str) -> int:
    """Get the recommended fetch interval for a source based on its history.

    Rules (smarter adaptive scheduling):
    - 5+ consecutive errors → 720 min (12h backoff) + temporarily disable
    - 3-4 consecutive errors → 360 min (6h backoff)
    - 1-2 consecutive errors → 180 min
    - Last fetch yielded 0 AND total 0 jobs ever → 480 min (8h, dead source)
    - Last fetch yielded 0 AND has history → 240 min (cooling off)
    - Last 3 fetches all yielded 0 → 360 min (slow down)
    - Last fetch yielded 50+ jobs → 30 min (very hot source)
    - Last fetch yielded 20+ jobs → 45 min (hot source)
    - Last fetch yielded 5+ jobs → 60 min (productive)
    - Default: 120 min
    """
    conn = get_db()
    try:
        row = conn.execute(
            """SELECT consecutive_errors, last_job_count, total_jobs_found,
                      enabled, fetch_interval_minutes
               FROM discovery_sources WHERE source_name=?""",
            (source_name,),
        ).fetchone()
        if not row:
            return 120  # New source, use default

        errors = row["consecutive_errors"] or 0

        # Error-based backoff
        if errors >= 5:
            # Temporarily disable: mark source as disabled after 5 consecutive errors
            try:
                conn.execute(
                    "UPDATE discovery_sources SET enabled=0, fetch_interval_minutes=720 WHERE source_name=?",
                    (source_name,),
                )
                conn.commit()
            except Exception:
                pass
            return 720  # 12h
        if errors >= 3:
            return 360  # 6h
        if errors >= 1:
            return 180  # 3h

        # Yield-based intervals
        last_count = row["last_job_count"] or 0
        total = row["total_jobs_found"] or 0

        if last_count == 0 and total == 0:
            return 480  # Dead source — check every 8h
        if last_count == 0:
            return 240  # Recently dry — slow down
        if last_count >= 50:
            return 30   # Very hot source — poll every 30 min
        if last_count >= 20:
            return 45   # Hot source
        if last_count >= 5:
            return 60   # Productive
        return 120  # Normal cadence
    except Exception:
        return 120
    finally:
        conn.close()


def should_fetch_source(source_name: str) -> bool:
    """Check if enough time has passed since last fetch for this source.

    Uses adaptive intervals based on source history.
    Skips disabled sources (consecutive_errors >= 5).
    """
    conn = get_db()
    try:
        row = conn.execute(
            """SELECT last_fetched_at, consecutive_errors, last_job_count,
                      total_jobs_found, enabled
               FROM discovery_sources WHERE source_name=?""",
            (source_name,),
        ).fetchone()
        if not row or not row["last_fetched_at"]:
            return True  # Never fetched — always fetch

        # Skip if explicitly disabled (too many errors)
        if row["enabled"] == 0:
            return False

        interval = get_adaptive_interval(source_name)
        last_fetch = datetime.fromisoformat(row["last_fetched_at"])
        return datetime.now() - last_fetch >= timedelta(minutes=interval)
    except Exception:
        return True  # Fetch on error (safe default)
    finally:
        conn.close()


def reenable_source(source_name: str) -> None:
    """Re-enable a source that was disabled due to errors (e.g., after manual check)."""
    conn = get_db()
    try:
        conn.execute(
            """UPDATE discovery_sources
               SET enabled=1, consecutive_errors=0, fetch_interval_minutes=120
               WHERE source_name=?""",
            (source_name,),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Pipeline Health Metrics
# ---------------------------------------------------------------------------

def get_pipeline_health() -> dict:
    """Compute pipeline health metrics.

    Returns:
        jobs_per_day: new jobs ingested in last 24h
        jobs_per_hour: new jobs ingested in last 1h
        sources_total: total enabled sources
        sources_failing: sources with consecutive_errors >= 1
        sources_disabled: sources with enabled=0
        sources_dry: sources with last_job_count=0 and total>0
        avg_freshness_hours: avg hours between posting_at and first_seen_at
        alert_success_rate: pct of alertable jobs that were alerted
        pipeline_healthy: True if jobs_per_day > 0 and sources_failing < 50%
    """
    conn = get_db()
    try:
        now = datetime.now()
        day_cutoff = (now - timedelta(hours=24)).isoformat()
        hour_cutoff = (now - timedelta(hours=1)).isoformat()

        jobs_day = conn.execute(
            "SELECT COUNT(*) as cnt FROM discovered_jobs WHERE first_seen_at >= ? AND is_backfill=0",
            (day_cutoff,),
        ).fetchone()["cnt"]

        jobs_hour = conn.execute(
            "SELECT COUNT(*) as cnt FROM discovered_jobs WHERE first_seen_at >= ? AND is_backfill=0",
            (hour_cutoff,),
        ).fetchone()["cnt"]

        # Source health
        src_stats = conn.execute(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN enabled=0 THEN 1 ELSE 0 END) as disabled,
                SUM(CASE WHEN consecutive_errors >= 1 AND enabled=1 THEN 1 ELSE 0 END) as failing,
                SUM(CASE WHEN last_job_count=0 AND total_jobs_found > 0 AND enabled=1 THEN 1 ELSE 0 END) as dry
               FROM discovery_sources"""
        ).fetchone()

        # Alert success rate: of jobs that could be alerted (new, not backfill),
        # what fraction were actually alerted?
        alertable = conn.execute(
            """SELECT COUNT(*) as cnt FROM discovered_jobs
               WHERE is_backfill=0 AND first_seen_at >= ?""",
            (day_cutoff,),
        ).fetchone()["cnt"]

        alerted = conn.execute(
            """SELECT COUNT(*) as cnt FROM discovered_jobs
               WHERE is_backfill=0 AND alert_status='sent' AND first_seen_at >= ?""",
            (day_cutoff,),
        ).fetchone()["cnt"]

        alert_rate = (alerted / alertable) if alertable > 0 else 0.0

        # Freshness: avg delay from posting_at to first_seen_at (hours)
        # Only for jobs where posting_at is set and not empty
        fresh_rows = conn.execute(
            """SELECT first_seen_at, posted_at FROM discovered_jobs
               WHERE posted_at != '' AND first_seen_at != ''
               ORDER BY first_seen_at DESC LIMIT 500"""
        ).fetchall()
        delays = []
        for row in fresh_rows:
            try:
                seen = datetime.fromisoformat(row["first_seen_at"])
                posted = datetime.fromisoformat(row["posted_at"])
                delay_h = (seen - posted).total_seconds() / 3600
                if 0 <= delay_h <= 720:  # Ignore outliers > 30 days
                    delays.append(delay_h)
            except Exception:
                pass
        avg_freshness = sum(delays) / len(delays) if delays else None

        total_src = src_stats["total"] or 0
        failing_src = src_stats["failing"] or 0

        return {
            "jobs_per_day": jobs_day,
            "jobs_per_hour": jobs_hour,
            "sources_total": total_src,
            "sources_failing": failing_src,
            "sources_disabled": src_stats["disabled"] or 0,
            "sources_dry": src_stats["dry"] or 0,
            "avg_freshness_hours": round(avg_freshness, 1) if avg_freshness is not None else None,
            "alert_success_rate": round(alert_rate * 100, 1),
            "alerted_today": alerted,
            "alertable_today": alertable,
            "pipeline_healthy": jobs_day > 0 and (failing_src < total_src * 0.5 if total_src else False),
        }
    except Exception as e:
        logger.warning(f"Pipeline health check failed: {e}")
        return {"pipeline_healthy": False, "error": str(e)}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Full-Text Search (FTS5)
# ---------------------------------------------------------------------------

def search_fts(query: str, limit: int = 50) -> list[dict]:
    """Full-text search using SQLite FTS5.

    Much faster than LIKE %keyword% for large databases.
    Falls back to LIKE if FTS5 is not available.
    """
    conn = get_db()
    try:
        # Try FTS5 first
        try:
            rows = conn.execute(
                """SELECT d.* FROM jobs_fts f
                   JOIN discovered_jobs d ON d.rowid = f.rowid
                   WHERE jobs_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            # FTS5 not available or not populated — fall back to LIKE
            kw = f"%{query}%"
            rows = conn.execute(
                """SELECT * FROM discovered_jobs
                   WHERE title LIKE ? OR description LIKE ? OR skills LIKE ?
                   ORDER BY match_score DESC LIMIT ?""",
                (kw, kw, kw, limit),
            ).fetchall()
            return [dict(r) for r in rows]
    finally:
        conn.close()


def rebuild_fts_index() -> int:
    """Rebuild the FTS5 index from the discovered_jobs table.

    Call this periodically or after bulk inserts.
    Uses the FTS5 'rebuild' command for content-external tables.
    """
    conn = get_db()
    try:
        conn.execute("INSERT INTO jobs_fts(jobs_fts) VALUES('rebuild')")
        conn.commit()
        count = conn.execute("SELECT COUNT(*) as cnt FROM jobs_fts").fetchone()["cnt"]
        logger.info(f"FTS index rebuilt with {count} jobs")
        return count
    except Exception as e:
        logger.debug(f"FTS rebuild failed (may not be available): {e}")
        return 0
    finally:
        conn.close()
