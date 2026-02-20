"""Automated database backup and rotation.

Protects against data loss by:
- Creating daily SQLite backups
- Rotating: keep 7 daily + 4 weekly backups
- Pre-migration snapshots
- Health reporting (last backup time, DB size)
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from src.config import PROJECT_ROOT
from src.utils.logging import get_logger

logger = get_logger(__name__)

BACKUP_DIR = PROJECT_ROOT / "data" / "backups"
DB_PATH = PROJECT_ROOT / "data" / "discovered_jobs.db"

MAX_DAILY_BACKUPS = 7
MAX_WEEKLY_BACKUPS = 4


def backup_database(
    db_path: Path | None = None,
    backup_dir: Path | None = None,
    label: str = "",
) -> Path | None:
    """Create a backup of the SQLite database.

    Uses SQLite's backup API for safe, consistent copies even while
    the database is being written to.

    Args:
        db_path: Path to the database file. Defaults to discovered_jobs.db.
        backup_dir: Where to store backups. Defaults to data/backups/.
        label: Optional label suffix (e.g. "pre-migration").

    Returns:
        Path to the backup file, or None if backup failed.
    """
    db_path = db_path or DB_PATH
    backup_dir = backup_dir or BACKUP_DIR

    if not db_path.exists():
        logger.warning(f"Database not found: {db_path}")
        return None

    backup_dir.mkdir(parents=True, exist_ok=True)

    # Build filename
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    suffix = f"-{label}" if label else ""
    filename = f"{date_str}{suffix}.db"
    backup_path = backup_dir / filename

    # If today's backup already exists (and no special label), skip
    if backup_path.exists() and not label:
        logger.debug(f"Today's backup already exists: {backup_path}")
        return backup_path

    try:
        # Use SQLite backup API for consistent copy
        source = sqlite3.connect(str(db_path))
        dest = sqlite3.connect(str(backup_path))
        source.backup(dest)
        dest.close()
        source.close()

        size_mb = backup_path.stat().st_size / (1024 * 1024)
        logger.info(f"Backup created: {backup_path.name} ({size_mb:.1f} MB)")
        return backup_path

    except Exception as e:
        logger.error(f"Backup failed: {e}")
        # Try simple file copy as fallback
        try:
            shutil.copy2(str(db_path), str(backup_path))
            logger.info(f"Backup created (file copy fallback): {backup_path.name}")
            return backup_path
        except Exception as e2:
            logger.error(f"Backup file copy also failed: {e2}")
            return None


def rotate_backups(backup_dir: Path | None = None) -> dict:
    """Rotate old backups: keep 7 daily + 4 weekly.

    Returns dict with counts of kept and deleted backups.
    """
    backup_dir = backup_dir or BACKUP_DIR
    if not backup_dir.exists():
        return {"kept": 0, "deleted": 0}

    all_backups = sorted(backup_dir.glob("*.db"), key=lambda p: p.name, reverse=True)

    # Separate labeled backups (pre-migration, etc.) — always keep
    regular = []
    labeled = []
    for p in all_backups:
        # Regular backups match YYYY-MM-DD.db
        name = p.stem
        if len(name) == 10 and name[4] == "-" and name[7] == "-":
            regular.append(p)
        else:
            labeled.append(p)

    # Keep first 7 daily
    keep_daily = set(regular[:MAX_DAILY_BACKUPS])

    # Keep weekly (one per week for the last 4 weeks)
    keep_weekly: set[Path] = set()
    now = datetime.now()
    for week_offset in range(MAX_WEEKLY_BACKUPS):
        target_date = now - timedelta(weeks=week_offset + 1)
        # Find the closest backup to this week's target
        best: Path | None = None
        best_diff = timedelta(days=999)
        for p in regular:
            try:
                backup_date = datetime.strptime(p.stem[:10], "%Y-%m-%d")
                diff = abs(backup_date - target_date)
                if diff < best_diff:
                    best_diff = diff
                    best = p
            except ValueError:
                continue
        if best:
            keep_weekly.add(best)

    # Union of all keepers
    keep = keep_daily | keep_weekly | set(labeled)
    to_delete = [p for p in all_backups if p not in keep]

    deleted = 0
    for p in to_delete:
        try:
            p.unlink()
            deleted += 1
            logger.debug(f"Deleted old backup: {p.name}")
        except Exception as e:
            logger.warning(f"Failed to delete backup {p.name}: {e}")

    logger.info(f"Backup rotation: kept {len(keep)}, deleted {deleted}")
    return {"kept": len(keep), "deleted": deleted}


def get_backup_health(
    db_path: Path | None = None,
    backup_dir: Path | None = None,
) -> dict:
    """Get health status of database and backups.

    Returns dict with:
    - db_exists: bool
    - db_size_mb: float
    - db_row_count: int (discovered_jobs)
    - last_backup: ISO string or None
    - hours_since_backup: float
    - backup_count: int
    - status: "ok", "warning", "critical"
    """
    db_path = db_path or DB_PATH
    backup_dir = backup_dir or BACKUP_DIR

    health: dict = {
        "db_exists": db_path.exists(),
        "db_size_mb": 0.0,
        "db_row_count": 0,
        "last_backup": None,
        "hours_since_backup": 999.0,
        "backup_count": 0,
        "status": "critical",
    }

    if db_path.exists():
        health["db_size_mb"] = round(db_path.stat().st_size / (1024 * 1024), 2)
        try:
            conn = sqlite3.connect(str(db_path))
            count = conn.execute("SELECT COUNT(*) FROM discovered_jobs").fetchone()[0]
            health["db_row_count"] = count
            conn.close()
        except Exception:
            pass

    if backup_dir.exists():
        backups = sorted(backup_dir.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        health["backup_count"] = len(backups)
        if backups:
            last_mtime = datetime.fromtimestamp(backups[0].stat().st_mtime)
            health["last_backup"] = last_mtime.isoformat()
            health["hours_since_backup"] = (datetime.now() - last_mtime).total_seconds() / 3600

    # Determine status
    if health["hours_since_backup"] <= 24:
        health["status"] = "ok"
    elif health["hours_since_backup"] <= 48:
        health["status"] = "warning"
    else:
        health["status"] = "critical"

    return health
