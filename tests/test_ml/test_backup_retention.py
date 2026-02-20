"""Tests for backup and retention utilities."""

import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch

from src.utils.backup import backup_database, get_backup_health, rotate_backups
from src.utils.retention import (
    archive_old_jobs,
    ensure_archive_table,
    get_retention_stats,
    vacuum_database,
    PROTECTED_STATUSES,
    ARCHIVABLE_STATUSES,
)


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary database with sample data."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE discovered_jobs (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            company TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL UNIQUE,
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
            updated_at TEXT DEFAULT ''
        )
    """)

    # Insert sample data: mix of old and new, protected and archivable
    jobs = [
        ("j1", "Engineer A", "CompA", "https://a.com/1", "new", "2024-01-01T00:00:00"),      # old, archivable
        ("j2", "Engineer B", "CompB", "https://b.com/2", "new", "2024-02-01T00:00:00"),      # old, archivable
        ("j3", "Engineer C", "CompC", "https://c.com/3", "dismissed", "2024-03-01T00:00:00"), # old, archivable
        ("j4", "Engineer D", "CompD", "https://d.com/4", "applied", "2024-01-01T00:00:00"),   # old, PROTECTED
        ("j5", "Engineer E", "CompE", "https://e.com/5", "saved", "2024-01-01T00:00:00"),     # old, PROTECTED
        ("j6", "Engineer F", "CompF", "https://f.com/6", "new", "2026-02-19T00:00:00"),       # recent, archivable but too new
    ]
    for job_id, title, company, url, status, discovered in jobs:
        conn.execute(
            "INSERT INTO discovered_jobs (id, title, company, url, status, discovered_at) VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, title, company, url, status, discovered),
        )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def tmp_backup_dir(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    return backup_dir


class TestBackup:
    """Test database backup."""

    def test_backup_creates_file(self, tmp_db, tmp_backup_dir):
        result = backup_database(db_path=tmp_db, backup_dir=tmp_backup_dir)
        assert result is not None
        assert result.exists()

    def test_backup_is_valid_db(self, tmp_db, tmp_backup_dir):
        backup_path = backup_database(db_path=tmp_db, backup_dir=tmp_backup_dir)
        conn = sqlite3.connect(str(backup_path))
        count = conn.execute("SELECT COUNT(*) FROM discovered_jobs").fetchone()[0]
        conn.close()
        assert count == 6

    def test_backup_with_label(self, tmp_db, tmp_backup_dir):
        result = backup_database(db_path=tmp_db, backup_dir=tmp_backup_dir, label="pre-migration")
        assert "pre-migration" in result.name

    def test_backup_nonexistent_db(self, tmp_path, tmp_backup_dir):
        result = backup_database(db_path=tmp_path / "nonexistent.db", backup_dir=tmp_backup_dir)
        assert result is None


class TestRotation:
    """Test backup rotation."""

    def test_rotation_deletes_old(self, tmp_backup_dir):
        # Create 15 daily backups
        for i in range(15):
            day = f"2026-01-{i+1:02d}.db"
            (tmp_backup_dir / day).write_bytes(b"fake db")

        result = rotate_backups(backup_dir=tmp_backup_dir)
        assert result["deleted"] > 0
        remaining = list(tmp_backup_dir.glob("*.db"))
        assert len(remaining) <= 11  # 7 daily + 4 weekly

    def test_rotation_keeps_labeled(self, tmp_backup_dir):
        (tmp_backup_dir / "2026-01-01-pre-migration.db").write_bytes(b"labeled")
        (tmp_backup_dir / "2024-01-01.db").write_bytes(b"old")

        rotate_backups(backup_dir=tmp_backup_dir)
        assert (tmp_backup_dir / "2026-01-01-pre-migration.db").exists()


class TestBackupHealth:
    """Test health reporting."""

    def test_health_with_backup(self, tmp_db, tmp_backup_dir):
        backup_database(db_path=tmp_db, backup_dir=tmp_backup_dir)
        health = get_backup_health(db_path=tmp_db, backup_dir=tmp_backup_dir)
        assert health["db_exists"] is True
        assert health["db_row_count"] == 6
        assert health["backup_count"] == 1
        assert health["status"] == "ok"

    def test_health_without_backup(self, tmp_db, tmp_backup_dir):
        health = get_backup_health(db_path=tmp_db, backup_dir=tmp_backup_dir)
        assert health["status"] == "critical"
        assert health["backup_count"] == 0


class TestRetention:
    """Test retention policy and archival."""

    def test_archive_old_jobs(self, tmp_db):
        result = archive_old_jobs(retention_days=90, db_path=tmp_db)
        # j1, j2, j3 are old + archivable => archived
        # j4, j5 are old but PROTECTED => NOT archived
        # j6 is new => NOT archived
        assert result["archived"] == 3

    def test_protected_statuses_not_archived(self, tmp_db):
        archive_old_jobs(retention_days=90, db_path=tmp_db)
        conn = sqlite3.connect(str(tmp_db))
        remaining = conn.execute("SELECT id, status FROM discovered_jobs").fetchall()
        conn.close()
        remaining_statuses = {r[1] for r in remaining}
        # Applied and saved should still be in main table
        assert "applied" in remaining_statuses
        assert "saved" in remaining_statuses

    def test_recent_jobs_not_archived(self, tmp_db):
        archive_old_jobs(retention_days=90, db_path=tmp_db)
        conn = sqlite3.connect(str(tmp_db))
        remaining_ids = {r[0] for r in conn.execute("SELECT id FROM discovered_jobs").fetchall()}
        conn.close()
        assert "j6" in remaining_ids  # recent "new" job stays

    def test_archived_jobs_in_archive_table(self, tmp_db):
        archive_old_jobs(retention_days=90, db_path=tmp_db)
        conn = sqlite3.connect(str(tmp_db))
        archived = conn.execute("SELECT COUNT(*) FROM archived_jobs").fetchone()[0]
        conn.close()
        assert archived == 3

    def test_no_eligible_jobs(self, tmp_db):
        # Archive everything first, then try again
        archive_old_jobs(retention_days=90, db_path=tmp_db)
        result = archive_old_jobs(retention_days=90, db_path=tmp_db)
        assert result["archived"] == 0


class TestVacuum:
    """Test VACUUM operation."""

    def test_vacuum_runs(self, tmp_db):
        result = vacuum_database(db_path=tmp_db)
        assert "before_mb" in result
        assert "after_mb" in result


class TestRetentionStats:
    """Test retention statistics."""

    def test_stats_before_archival(self, tmp_db):
        stats = get_retention_stats(db_path=tmp_db)
        assert stats["total_active"] == 6
        assert stats["total_archived"] == 0

    def test_stats_after_archival(self, tmp_db):
        archive_old_jobs(retention_days=90, db_path=tmp_db)
        stats = get_retention_stats(db_path=tmp_db)
        assert stats["total_active"] == 3
        assert stats["total_archived"] == 3


class TestProtectedStatuses:
    """Test that protected status constants are correct."""

    def test_applied_is_protected(self):
        assert "applied" in PROTECTED_STATUSES

    def test_saved_is_protected(self):
        assert "saved" in PROTECTED_STATUSES

    def test_new_is_archivable(self):
        assert "new" in ARCHIVABLE_STATUSES

    def test_no_overlap(self):
        assert PROTECTED_STATUSES.isdisjoint(ARCHIVABLE_STATUSES)
