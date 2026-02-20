"""Variant store — saves resume variants separately, NEVER overwrites originals.

Design principles:
- Every rewritten resume is stored as a NEW variant
- Original resumes are NEVER modified or deleted by the system
- Each variant links back to its parent resume_id
- Variants track which JD they were optimized for
- Approval status per bullet (approved/rejected/pending)
- Performance tracking: which variants got interviews

Intelligence metadata per variant:
- match_score, weighted_score, coverage_rate
- exact_match_count, transferable_count, gap_count
- platform_alignment_score, validation_pass_rate

Per-bullet validation:
- word_count_ok, no_new_skills_ok, metrics_preserved_ok
- semantic_similarity_score, action_verb_ok

Status state machine:
  draft → partially_reviewed → finalized → exported → applied → archived

Finalization rules:
  approved → use rewritten (or user_edited_text if present)
  rejected → use original
  pending  → variant stays in draft/partially_reviewed, cannot finalize

Audit trail:
  created_at, reviewed_at, finalized_at, exported_at, applied_at, archived_at
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from src.utils.logging import get_logger

logger = get_logger(__name__)

# Variant DB lives alongside resume DB but is a SEPARATE file
VARIANT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "variants.db"

# Valid status transitions
VALID_STATUSES = ("draft", "partially_reviewed", "finalized", "exported", "applied", "archived")
_ALLOWED_TRANSITIONS = {
    "draft": ("partially_reviewed", "finalized", "archived"),
    "partially_reviewed": ("finalized", "draft", "archived"),
    "finalized": ("exported", "draft", "archived"),
    "exported": ("applied", "finalized", "archived"),
    "applied": ("archived",),
    "archived": ("draft",),  # Can unarchive back to draft
}


def _get_conn(db_path: Path | None = None) -> sqlite3.Connection:
    """Get a connection to the variant database."""
    path = db_path or VARIANT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_variant_db(db_path: Path | None = None) -> None:
    """Initialize the variant database schema."""
    conn = _get_conn(db_path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS variants (
                id TEXT PRIMARY KEY,
                parent_resume_id TEXT NOT NULL,
                jd_title TEXT DEFAULT '',
                jd_company TEXT DEFAULT '',
                jd_text TEXT DEFAULT '',
                method TEXT DEFAULT 'deterministic',

                -- Status state machine
                status TEXT DEFAULT 'draft',

                -- Audit trail timestamps
                created_at TEXT NOT NULL,
                reviewed_at TEXT DEFAULT NULL,
                finalized_at TEXT DEFAULT NULL,
                exported_at TEXT DEFAULT NULL,
                applied_at TEXT DEFAULT NULL,
                archived_at TEXT DEFAULT NULL,

                -- JD snapshot (for later analytics)
                jd_skills_json TEXT DEFAULT '[]',
                jd_cleaned_text TEXT DEFAULT '',

                -- Resume version tracking
                resume_hash TEXT DEFAULT '',
                resume_version TEXT DEFAULT '',

                -- Intelligence metadata (scoring)
                match_score REAL DEFAULT 0.0,
                weighted_score REAL DEFAULT 0.0,
                coverage_rate REAL DEFAULT 0.0,
                exact_match_count INTEGER DEFAULT 0,
                transferable_count INTEGER DEFAULT 0,
                gap_count INTEGER DEFAULT 0,
                platform_alignment_score REAL DEFAULT 0.0,
                validation_pass_rate REAL DEFAULT 0.0,

                -- Rich data (JSON blobs)
                bullets_json TEXT DEFAULT '[]',
                diff_report_json TEXT DEFAULT '{}',
                gap_analysis_json TEXT DEFAULT '{}',
                notes TEXT DEFAULT '',

                -- Performance tracking
                interview_callback INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS variant_bullets (
                id TEXT PRIMARY KEY,
                variant_id TEXT NOT NULL,
                bullet_index INTEGER NOT NULL,
                original_text TEXT NOT NULL,
                rewritten_text TEXT NOT NULL,

                -- Approval workflow
                approval TEXT DEFAULT 'pending',
                user_edited_text TEXT DEFAULT NULL,
                approved_at TEXT DEFAULT NULL,

                -- Changes made
                changes_json TEXT DEFAULT '[]',

                -- Per-bullet validation results
                word_count_ok INTEGER DEFAULT 1,
                no_new_skills_ok INTEGER DEFAULT 1,
                metrics_preserved_ok INTEGER DEFAULT 1,
                semantic_similarity_score REAL DEFAULT 1.0,
                action_verb_ok INTEGER DEFAULT 1,
                platform_swap_ok INTEGER DEFAULT 1,
                validation_passed INTEGER DEFAULT 1,
                validation_errors_json TEXT DEFAULT '[]',

                -- Performance tracking per bullet
                effectiveness_score REAL DEFAULT NULL,

                FOREIGN KEY (variant_id) REFERENCES variants(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_variants_parent
                ON variants(parent_resume_id);
            CREATE INDEX IF NOT EXISTS idx_variants_status
                ON variants(status);
            CREATE INDEX IF NOT EXISTS idx_variant_bullets_variant
                ON variant_bullets(variant_id);
        """)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Variant CRUD
# ---------------------------------------------------------------------------

def save_variant(
    parent_resume_id: str,
    jd_title: str = "",
    jd_company: str = "",
    jd_text: str = "",
    method: str = "deterministic",
    bullets: list[dict] | None = None,
    diff_report: dict | None = None,
    gap_analysis: dict | None = None,
    notes: str = "",
    # JD snapshot
    jd_skills: list[str] | None = None,
    jd_cleaned_text: str = "",
    # Resume version tracking
    resume_hash: str = "",
    resume_version: str = "",
    # Intelligence metadata
    match_score: float = 0.0,
    weighted_score: float = 0.0,
    coverage_rate: float = 0.0,
    exact_match_count: int = 0,
    transferable_count: int = 0,
    gap_count: int = 0,
    platform_alignment_score: float = 0.0,
    validation_pass_rate: float = 0.0,
    db_path: Path | None = None,
) -> dict:
    """Save a new resume variant. NEVER overwrites an existing variant."""
    conn = _get_conn(db_path)
    try:
        init_variant_db(db_path)
        variant_id = str(uuid.uuid4())[:8]
        now = datetime.utcnow().isoformat()

        conn.execute(
            """INSERT INTO variants
               (id, parent_resume_id, jd_title, jd_company, jd_text, method,
                status, created_at, bullets_json, diff_report_json,
                gap_analysis_json, notes,
                jd_skills_json, jd_cleaned_text,
                resume_hash, resume_version,
                match_score, weighted_score, coverage_rate,
                exact_match_count, transferable_count, gap_count,
                platform_alignment_score, validation_pass_rate)
               VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                variant_id, parent_resume_id, jd_title, jd_company, jd_text,
                method, now,
                json.dumps(bullets or []),
                json.dumps(diff_report or {}),
                json.dumps(gap_analysis or {}),
                notes,
                json.dumps(jd_skills or []),
                jd_cleaned_text,
                resume_hash, resume_version,
                match_score, weighted_score, coverage_rate,
                exact_match_count, transferable_count, gap_count,
                platform_alignment_score, validation_pass_rate,
            ),
        )

        # Save individual bullets with per-bullet validation
        if bullets:
            for i, b in enumerate(bullets):
                bullet_id = f"{variant_id}_b{i}"
                v = b.get("validation", {})
                conn.execute(
                    """INSERT INTO variant_bullets
                       (id, variant_id, bullet_index, original_text,
                        rewritten_text, approval, changes_json,
                        word_count_ok, no_new_skills_ok, metrics_preserved_ok,
                        semantic_similarity_score, action_verb_ok,
                        platform_swap_ok, validation_passed,
                        validation_errors_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        bullet_id, variant_id, i,
                        b.get("original_text", ""),
                        b.get("rewritten_text", b.get("original_text", "")),
                        b.get("approval", "pending"),
                        json.dumps(b.get("changes", [])),
                        int(v.get("word_count_ok", True)),
                        int(v.get("no_new_skills_ok", True)),
                        int(v.get("metrics_preserved_ok", True)),
                        float(v.get("semantic_similarity_score", 1.0)),
                        int(v.get("action_verb_ok", True)),
                        int(v.get("platform_swap_ok", True)),
                        int(v.get("validation_passed", True)),
                        json.dumps(v.get("errors", [])),
                    ),
                )

        conn.commit()

        logger.info(
            f"Saved variant {variant_id} for resume {parent_resume_id} "
            f"({len(bullets or [])} bullets, score={weighted_score:.2f})"
        )

        return {
            "id": variant_id,
            "parent_resume_id": parent_resume_id,
            "jd_title": jd_title,
            "jd_company": jd_company,
            "method": method,
            "created_at": now,
            "status": "draft",
            "bullet_count": len(bullets or []),
            "match_score": match_score,
            "weighted_score": weighted_score,
            "coverage_rate": coverage_rate,
        }
    finally:
        conn.close()


def get_variant(variant_id: str, db_path: Path | None = None) -> dict | None:
    """Get a variant with all its bullets and metadata."""
    conn = _get_conn(db_path)
    try:
        init_variant_db(db_path)
        row = conn.execute(
            "SELECT * FROM variants WHERE id = ?", (variant_id,)
        ).fetchone()

        if not row:
            return None

        result = dict(row)
        # Parse JSON fields
        result["bullets"] = json.loads(result.pop("bullets_json", "[]"))
        result["diff_report"] = json.loads(result.pop("diff_report_json", "{}"))
        result["gap_analysis"] = json.loads(result.pop("gap_analysis_json", "{}"))

        # Get bullet details with validation
        bullet_rows = conn.execute(
            """SELECT * FROM variant_bullets
               WHERE variant_id = ? ORDER BY bullet_index""",
            (variant_id,),
        ).fetchall()

        result["bullet_details"] = []
        for br in bullet_rows:
            bd = dict(br)
            bd["changes"] = json.loads(bd.pop("changes_json", "[]"))
            bd["validation_errors"] = json.loads(bd.pop("validation_errors_json", "[]"))
            # Convert SQLite integers back to bools for validation flags
            for flag in ("word_count_ok", "no_new_skills_ok", "metrics_preserved_ok",
                        "action_verb_ok", "platform_swap_ok", "validation_passed"):
                bd[flag] = bool(bd.get(flag, 1))
            result["bullet_details"].append(bd)

        return result
    finally:
        conn.close()


def list_variants(
    parent_resume_id: str | None = None,
    status: str | None = None,
    db_path: Path | None = None,
) -> list[dict]:
    """List variants, optionally filtered by parent resume or status."""
    conn = _get_conn(db_path)
    try:
        init_variant_db(db_path)
        query = (
            "SELECT id, parent_resume_id, jd_title, jd_company, method, "
            "status, created_at, finalized_at, applied_at, "
            "match_score, weighted_score, coverage_rate, "
            "exact_match_count, transferable_count, gap_count, "
            "validation_pass_rate, interview_callback "
            "FROM variants"
        )
        params: list = []
        conditions = []

        if parent_resume_id:
            conditions.append("parent_resume_id = ?")
            params.append(parent_resume_id)
        if status:
            conditions.append("status = ?")
            params.append(status)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY created_at DESC"

        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_bullet_approval(
    variant_id: str,
    bullet_index: int,
    approval: str,
    user_edited_text: str | None = None,
    db_path: Path | None = None,
) -> bool:
    """Update approval status for a specific bullet.

    approval: 'approved', 'rejected', 'pending'
    user_edited_text: If the user manually edited the text
    """
    if approval not in ("approved", "rejected", "pending"):
        return False

    conn = _get_conn(db_path)
    try:
        init_variant_db(db_path)
        bullet_id = f"{variant_id}_b{bullet_index}"
        now = datetime.utcnow().isoformat()

        if user_edited_text is not None:
            conn.execute(
                """UPDATE variant_bullets
                   SET approval = ?, user_edited_text = ?, approved_at = ?
                   WHERE id = ?""",
                (approval, user_edited_text, now if approval == "approved" else None, bullet_id),
            )
        else:
            conn.execute(
                """UPDATE variant_bullets
                   SET approval = ?, approved_at = ?
                   WHERE id = ?""",
                (approval, now if approval == "approved" else None, bullet_id),
            )

        rows_changed = conn.execute("SELECT changes() AS c").fetchone()["c"]

        # Auto-update variant status based on bullet approvals
        if rows_changed > 0:
            _auto_update_variant_status(conn, variant_id)

        conn.commit()
        return rows_changed > 0
    finally:
        conn.close()


def _auto_update_variant_status(conn: sqlite3.Connection, variant_id: str) -> None:
    """Auto-update variant status based on bullet approvals.

    - All bullets approved/rejected → partially_reviewed
    - If already partially_reviewed and user hasn't finalized, keep it
    """
    current = conn.execute(
        "SELECT status FROM variants WHERE id = ?", (variant_id,)
    ).fetchone()
    if not current or current["status"] not in ("draft", "partially_reviewed"):
        return

    bullets = conn.execute(
        "SELECT approval FROM variant_bullets WHERE variant_id = ?",
        (variant_id,),
    ).fetchall()

    if not bullets:
        return

    pending_count = sum(1 for b in bullets if b["approval"] == "pending")
    total = len(bullets)

    now = datetime.utcnow().isoformat()

    if pending_count == 0:
        # All bullets reviewed
        conn.execute(
            "UPDATE variants SET status = 'partially_reviewed', reviewed_at = ? WHERE id = ? AND status = 'draft'",
            (now, variant_id),
        )
    elif pending_count < total and current["status"] == "draft":
        # Some bullets reviewed — move to partially_reviewed
        conn.execute(
            "UPDATE variants SET status = 'partially_reviewed', reviewed_at = ? WHERE id = ? AND status = 'draft'",
            (now, variant_id),
        )


def finalize_variant(
    variant_id: str,
    db_path: Path | None = None,
) -> dict | None:
    """Finalize a variant — build the final text from approved/edited bullets.

    Finalization rules:
    - approved → use rewritten (or user_edited_text if present)
    - rejected → use original
    - pending  → BLOCKS finalization (all bullets must be reviewed)

    Status: draft/partially_reviewed → finalized
    """
    conn = _get_conn(db_path)
    try:
        init_variant_db(db_path)
        variant = get_variant(variant_id, db_path)
        if not variant:
            return None

        # Check for pending bullets — must all be reviewed
        bullet_details = variant.get("bullet_details", [])
        pending = [bd for bd in bullet_details if bd["approval"] == "pending"]
        if pending:
            return {
                "error": "Cannot finalize: "
                         f"{len(pending)} bullet(s) still pending review",
                "pending_indices": [bd["bullet_index"] for bd in pending],
            }

        # Check status transition is valid
        if variant["status"] not in ("draft", "partially_reviewed"):
            if variant["status"] == "finalized":
                # Already finalized — just return it
                pass
            else:
                return {
                    "error": f"Cannot finalize from status '{variant['status']}'",
                }

        # Build final text from bullets
        final_bullets = []
        for bd in bullet_details:
            if bd["approval"] == "approved":
                # User edit takes priority over rewritten
                text = bd.get("user_edited_text") or bd["rewritten_text"]
            else:
                # Rejected → use original
                text = bd["original_text"]
            final_bullets.append({
                "index": bd["bullet_index"],
                "text": text,
                "source": "rewritten" if bd["approval"] == "approved" else "original",
                "approval": bd["approval"],
            })

        now = datetime.utcnow().isoformat()
        conn.execute(
            "UPDATE variants SET status = 'finalized', finalized_at = ? WHERE id = ?",
            (now, variant_id),
        )
        conn.commit()

        variant["status"] = "finalized"
        variant["finalized_at"] = now
        variant["final_bullets"] = final_bullets
        return variant
    finally:
        conn.close()


def transition_status(
    variant_id: str,
    new_status: str,
    db_path: Path | None = None,
) -> bool:
    """Transition variant to a new status (state machine enforced)."""
    if new_status not in VALID_STATUSES:
        return False

    conn = _get_conn(db_path)
    try:
        init_variant_db(db_path)
        row = conn.execute(
            "SELECT status FROM variants WHERE id = ?", (variant_id,)
        ).fetchone()
        if not row:
            return False

        current = row["status"]
        allowed = _ALLOWED_TRANSITIONS.get(current, ())
        if new_status not in allowed:
            logger.warning(
                f"Invalid transition: {current} → {new_status} "
                f"(allowed: {allowed})"
            )
            return False

        # Set the appropriate timestamp
        now = datetime.utcnow().isoformat()
        timestamp_col = {
            "partially_reviewed": "reviewed_at",
            "finalized": "finalized_at",
            "exported": "exported_at",
            "applied": "applied_at",
            "archived": "archived_at",
        }.get(new_status)

        if timestamp_col:
            conn.execute(
                f"UPDATE variants SET status = ?, {timestamp_col} = ? WHERE id = ?",
                (new_status, now, variant_id),
            )
        else:
            conn.execute(
                "UPDATE variants SET status = ? WHERE id = ?",
                (new_status, variant_id),
            )

        conn.commit()
        return True
    finally:
        conn.close()


def mark_interview_callback(
    variant_id: str,
    db_path: Path | None = None,
) -> bool:
    """Mark that this variant got an interview callback (performance tracking)."""
    conn = _get_conn(db_path)
    try:
        init_variant_db(db_path)
        conn.execute(
            "UPDATE variants SET interview_callback = 1 WHERE id = ?",
            (variant_id,),
        )
        rows = conn.execute("SELECT changes() AS c").fetchone()["c"]
        conn.commit()
        return rows > 0
    finally:
        conn.close()


def delete_variant(variant_id: str, db_path: Path | None = None) -> bool:
    """Delete a variant (but NEVER the original resume)."""
    conn = _get_conn(db_path)
    try:
        init_variant_db(db_path)
        conn.execute(
            "DELETE FROM variant_bullets WHERE variant_id = ?", (variant_id,)
        )
        conn.execute("DELETE FROM variants WHERE id = ?", (variant_id,))
        rows = conn.execute("SELECT changes() AS c").fetchone()["c"]
        conn.commit()
        return rows > 0
    finally:
        conn.close()


def get_variant_stats(db_path: Path | None = None) -> dict:
    """Get overall variant statistics for the dashboard."""
    conn = _get_conn(db_path)
    try:
        init_variant_db(db_path)
        total = conn.execute("SELECT COUNT(*) AS c FROM variants").fetchone()["c"]
        draft = conn.execute(
            "SELECT COUNT(*) AS c FROM variants WHERE status = 'draft'"
        ).fetchone()["c"]
        reviewed = conn.execute(
            "SELECT COUNT(*) AS c FROM variants WHERE status = 'partially_reviewed'"
        ).fetchone()["c"]
        finalized = conn.execute(
            "SELECT COUNT(*) AS c FROM variants WHERE status = 'finalized'"
        ).fetchone()["c"]
        exported = conn.execute(
            "SELECT COUNT(*) AS c FROM variants WHERE status = 'exported'"
        ).fetchone()["c"]
        applied = conn.execute(
            "SELECT COUNT(*) AS c FROM variants WHERE status = 'applied'"
        ).fetchone()["c"]
        archived = conn.execute(
            "SELECT COUNT(*) AS c FROM variants WHERE status = 'archived'"
        ).fetchone()["c"]
        interviews = conn.execute(
            "SELECT COUNT(*) AS c FROM variants WHERE interview_callback = 1"
        ).fetchone()["c"]

        # Average scores
        avg_row = conn.execute(
            "SELECT AVG(weighted_score) AS avg_ws, AVG(coverage_rate) AS avg_cr "
            "FROM variants WHERE weighted_score > 0"
        ).fetchone()

        # Validation analytics
        bullet_stats = conn.execute("""
            SELECT
                COUNT(*) AS total_bullets,
                SUM(CASE WHEN validation_passed = 1 THEN 1 ELSE 0 END) AS passed,
                SUM(CASE WHEN word_count_ok = 0 THEN 1 ELSE 0 END) AS word_count_fails,
                SUM(CASE WHEN no_new_skills_ok = 0 THEN 1 ELSE 0 END) AS new_skills_fails,
                SUM(CASE WHEN metrics_preserved_ok = 0 THEN 1 ELSE 0 END) AS metrics_fails,
                SUM(CASE WHEN platform_swap_ok = 0 THEN 1 ELSE 0 END) AS platform_fails,
                SUM(CASE WHEN action_verb_ok = 0 THEN 1 ELSE 0 END) AS action_verb_fails,
                AVG(semantic_similarity_score) AS avg_similarity
            FROM variant_bullets
        """).fetchone()

        return {
            "total_variants": total,
            "by_status": {
                "draft": draft,
                "partially_reviewed": reviewed,
                "finalized": finalized,
                "exported": exported,
                "applied": applied,
                "archived": archived,
            },
            "interviews": interviews,
            "interview_rate": interviews / max(applied, 1),
            "avg_weighted_score": round(avg_row["avg_ws"] or 0.0, 3),
            "avg_coverage_rate": round(avg_row["avg_cr"] or 0.0, 3),
            "bullet_analytics": {
                "total": bullet_stats["total_bullets"] or 0,
                "validation_pass_rate": (
                    (bullet_stats["passed"] or 0) / max(bullet_stats["total_bullets"] or 0, 1)
                ),
                "top_failure_reasons": {
                    "word_count": bullet_stats["word_count_fails"] or 0,
                    "new_skills": bullet_stats["new_skills_fails"] or 0,
                    "metrics_lost": bullet_stats["metrics_fails"] or 0,
                    "platform_swap": bullet_stats["platform_fails"] or 0,
                    "action_verb": bullet_stats["action_verb_fails"] or 0,
                },
                "avg_similarity": round(bullet_stats["avg_similarity"] or 0.0, 3),
            },
        }
    finally:
        conn.close()
