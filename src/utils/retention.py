"""Data retention policy for discovered jobs.

Manages the lifecycle of discovered jobs:
- "new" and "dismissed" jobs are archived after 90 days
- "saved", "applied", "tracked" jobs are NEVER auto-deleted (protected)
- Archived jobs move to `archived_jobs` table (still queryable)
- VACUUM runs after archival to reclaim disk space
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from src.config import PROJECT_ROOT
from src.utils.logging import get_logger

logger = get_logger(__name__)

DB_PATH = PROJECT_ROOT / "data" / "discovered_jobs.db"

# Statuses that are NEVER auto-archived
PROTECTED_STATUSES = {"saved", "applied", "tracked", "interested", "interview", "offer"}

# Statuses eligible for archival after retention period
ARCHIVABLE_STATUSES = {"new", "dismissed", "expired", "stale"}

DEFAULT_RETENTION_DAYS = 90


def _get_db(db_path: Path | None = None) -> sqlite3.Connection:
    """Get database connection."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_archive_table(db_path: Path | None = None) -> None:
    """Create the archived_jobs table if it doesn't exist.

    Has the same schema as discovered_jobs + an archived_at timestamp.
    """
    conn = _get_db(db_path)
    try:
        # Get the schema of discovered_jobs
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='discovered_jobs'"
        ).fetchone()

        if not row:
            logger.warning("discovered_jobs table not found, skipping archive table creation")
            return

        # Create archived_jobs with same schema + archived_at
        conn.execute("""
            CREATE TABLE IF NOT EXISTS archived_jobs (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                company TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL,
                description TEXT DEFAULT '',
                location TEXT DEFAULT '',
                source_name TEXT DEFAULT '',
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
                fingerprint TEXT DEFAULT '',
                ats_job_id TEXT DEFAULT '',
                match_score REAL DEFAULT 0.0,
                status TEXT DEFAULT 'new',
                parsed INTEGER DEFAULT 0,
                tracked INTEGER DEFAULT 0,
                applied_at TEXT DEFAULT '',
                first_seen_at TEXT DEFAULT '',
                last_seen_at TEXT DEFAULT '',
                posted_at TEXT DEFAULT '',
                discovered_at TEXT NOT NULL,
                parsed_at TEXT DEFAULT '',
                updated_at TEXT DEFAULT '',
                archived_at TEXT NOT NULL
            )
        """)
        conn.commit()
        logger.debug("Archive table ready")
    finally:
        conn.close()


def archive_old_jobs(
    retention_days: int = DEFAULT_RETENTION_DAYS,
    db_path: Path | None = None,
) -> dict:
    """Archive old jobs that meet the retention policy.

    - Only archives jobs with archivable statuses (new, dismissed, etc.)
    - NEVER archives protected statuses (saved, applied, tracked, etc.)
    - Moves data to archived_jobs table
    - Deletes from discovered_jobs

    Returns dict with archive stats.
    """
    ensure_archive_table(db_path)
    conn = _get_db(db_path)

    cutoff_date = (datetime.now() - timedelta(days=retention_days)).isoformat()

    # Build status filter
    archivable = tuple(ARCHIVABLE_STATUSES)
    placeholders = ",".join("?" for _ in archivable)

    try:
        # Count eligible jobs
        count = conn.execute(
            f"SELECT COUNT(*) FROM discovered_jobs "
            f"WHERE status IN ({placeholders}) AND discovered_at < ?",
            (*archivable, cutoff_date),
        ).fetchone()[0]

        if count == 0:
            logger.info("No jobs eligible for archival")
            return {"archived": 0, "retained": 0}

        now = datetime.now().isoformat()

        # Move to archive
        conn.execute(f"""
            INSERT OR IGNORE INTO archived_jobs
            SELECT *, ? as archived_at FROM discovered_jobs
            WHERE status IN ({placeholders}) AND discovered_at < ?
        """, (now, *archivable, cutoff_date))

        # Delete from main table
        deleted = conn.execute(
            f"DELETE FROM discovered_jobs "
            f"WHERE status IN ({placeholders}) AND discovered_at < ?",
            (*archivable, cutoff_date),
        ).rowcount

        conn.commit()

        # Count remaining
        remaining = conn.execute("SELECT COUNT(*) FROM discovered_jobs").fetchone()[0]

        logger.info(
            f"Archived {deleted} jobs (older than {retention_days} days). "
            f"{remaining} jobs remain in main table."
        )

        return {
            "archived": deleted,
            "retained": remaining,
            "cutoff_date": cutoff_date,
        }

    finally:
        conn.close()


def vacuum_database(db_path: Path | None = None) -> dict:
    """Run VACUUM to reclaim disk space.

    Should be run after archival. Returns size before/after.
    """
    path = db_path or DB_PATH
    if not path.exists():
        return {"before_mb": 0, "after_mb": 0, "saved_mb": 0}

    before_size = path.stat().st_size / (1024 * 1024)

    try:
        conn = sqlite3.connect(str(path))
        conn.execute("VACUUM")
        conn.close()
    except Exception as e:
        logger.error(f"VACUUM failed: {e}")
        return {"before_mb": round(before_size, 2), "after_mb": round(before_size, 2), "saved_mb": 0}

    after_size = path.stat().st_size / (1024 * 1024)
    saved = before_size - after_size

    logger.info(f"VACUUM: {before_size:.1f}MB -> {after_size:.1f}MB (saved {saved:.1f}MB)")

    return {
        "before_mb": round(before_size, 2),
        "after_mb": round(after_size, 2),
        "saved_mb": round(saved, 2),
    }


def get_retention_stats(db_path: Path | None = None) -> dict:
    """Get current retention statistics.

    Returns counts by status + archive info.
    """
    conn = _get_db(db_path)
    try:
        # Main table stats
        total = conn.execute("SELECT COUNT(*) FROM discovered_jobs").fetchone()[0]
        by_status = {}
        for row in conn.execute(
            "SELECT status, COUNT(*) as cnt FROM discovered_jobs GROUP BY status"
        ).fetchall():
            by_status[row["status"]] = row["cnt"]

        # Archive stats
        archived = 0
        try:
            archived = conn.execute("SELECT COUNT(*) FROM archived_jobs").fetchone()[0]
        except Exception:
            pass  # archive table may not exist

        protected_count = sum(by_status.get(s, 0) for s in PROTECTED_STATUSES)
        archivable_count = sum(by_status.get(s, 0) for s in ARCHIVABLE_STATUSES)

        return {
            "total_active": total,
            "total_archived": archived,
            "by_status": by_status,
            "protected_count": protected_count,
            "archivable_count": archivable_count,
        }
    finally:
        conn.close()
