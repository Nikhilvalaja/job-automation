"""Contact deduplication and merge logic.

Handles:
- Detecting duplicate contacts (same person, different email variants)
- Merging duplicate contacts (keep best data, redirect old ID)
- Name-based fuzzy matching for near-duplicates
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from src.crm.database import (
    _get_conn,
    init_crm_db,
    get_contact,
    list_contacts,
)
from src.utils.logging import get_logger
from pathlib import Path

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Email normalization
# ---------------------------------------------------------------------------

def normalize_email(email: str) -> str:
    """Normalize email for dedup comparison.

    - Lowercase
    - Strip dots from gmail local part (john.doe@ == johndoe@)
    - Strip + aliases (john+work@ == john@)
    """
    email = email.strip().lower()
    local, _, domain = email.partition("@")
    # Strip + alias
    local = local.split("+")[0]
    # Gmail: dots are ignored
    if domain in ("gmail.com", "googlemail.com"):
        local = local.replace(".", "")
    return f"{local}@{domain}"


def emails_are_same_person(email_a: str, email_b: str) -> bool:
    """Check if two emails likely belong to the same person."""
    return normalize_email(email_a) == normalize_email(email_b)


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    name = name.lower().strip()
    name = re.sub(r"[^a-z\s]", "", name)
    name = re.sub(r"\s+", " ", name)
    return name


def name_similarity(name_a: str, name_b: str) -> float:
    """SequenceMatcher similarity between normalized names."""
    a, b = normalize_name(name_a), normalize_name(name_b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

def find_duplicates(
    contact_id: str,
    db_path: Path | None = None,
) -> list[dict]:
    """Find potential duplicate contacts for a given contact.

    Checks:
    1. Normalized email match (different email string, same canonical form)
    2. Same company + high name similarity (≥ 0.85)

    Returns list of candidate duplicates with confidence scores.
    """
    contact = get_contact(contact_id, db_path=db_path)
    if not contact:
        return []

    all_contacts = list_contacts(limit=2000, db_path=db_path)
    candidates = []

    for other in all_contacts:
        if other["id"] == contact_id:
            continue
        if other.get("status") == "archived":
            continue

        confidence = 0.0
        reasons = []

        # Email normalization check
        if other.get("email") and contact.get("email"):
            if emails_are_same_person(contact["email"], other["email"]):
                confidence = max(confidence, 0.95)
                reasons.append("normalized_email_match")

        # Name + company match
        name_sim = name_similarity(
            contact.get("name", ""), other.get("name", "")
        )
        if name_sim >= 0.85:
            if (
                contact.get("company")
                and other.get("company")
                and contact["company"].lower().strip() == other["company"].lower().strip()
            ):
                confidence = max(confidence, 0.90)
                reasons.append(f"name_sim={name_sim:.2f}+same_company")
            elif name_sim >= 0.95:
                confidence = max(confidence, 0.75)
                reasons.append(f"name_sim={name_sim:.2f}")

        if confidence >= 0.70:
            candidates.append({
                "contact_id": other["id"],
                "name": other.get("name"),
                "email": other.get("email"),
                "company": other.get("company"),
                "confidence": confidence,
                "reasons": reasons,
            })

    candidates.sort(key=lambda x: x["confidence"], reverse=True)
    return candidates


# ---------------------------------------------------------------------------
# Contact merge
# ---------------------------------------------------------------------------

def merge_contacts(
    primary_id: str,
    secondary_id: str,
    db_path: Path | None = None,
) -> dict:
    """Merge secondary contact INTO primary contact.

    - Best data wins (non-empty fields from primary preferred)
    - Secondary's touchpoints and conversations are re-linked to primary
    - Secondary contact is archived (not deleted)

    Returns merged contact dict.
    """
    init_crm_db(db_path)
    conn = _get_conn(db_path)
    try:
        primary = get_contact(primary_id, db_path=db_path)
        secondary = get_contact(secondary_id, db_path=db_path)

        if not primary or not secondary:
            raise ValueError(f"Contact not found: {primary_id} or {secondary_id}")
        if primary_id == secondary_id:
            raise ValueError("Cannot merge contact with itself")

        from datetime import datetime
        now = datetime.utcnow().isoformat()

        # Build merged fields: primary wins if non-empty
        merged = {}
        for field in ("name", "company", "role", "notes", "linkedin_url"):
            merged[field] = primary.get(field) or secondary.get(field) or ""

        # Merge tags (union)
        primary_tags = set(primary.get("tags") or [])
        secondary_tags = set(secondary.get("tags") or [])
        merged["tags_json"] = str(list(primary_tags | secondary_tags)).replace("'", '"')

        # Keep earliest first_contacted_at
        p_first = primary.get("first_contacted_at")
        s_first = secondary.get("first_contacted_at")
        if p_first and s_first:
            merged["first_contacted_at"] = min(p_first, s_first)
        else:
            merged["first_contacted_at"] = p_first or s_first

        # Keep latest last_contacted_at
        p_last = primary.get("last_contacted_at")
        s_last = secondary.get("last_contacted_at")
        if p_last and s_last:
            merged["last_contacted_at"] = max(p_last, s_last)
        else:
            merged["last_contacted_at"] = p_last or s_last

        # Sum touchpoints
        merged["total_touchpoints"] = (
            (primary.get("total_touchpoints") or 0)
            + (secondary.get("total_touchpoints") or 0)
        )

        # Re-link secondary's touchpoints to primary
        conn.execute(
            "UPDATE touchpoints SET contact_id = ? WHERE contact_id = ?",
            (primary_id, secondary_id),
        )

        # Re-link secondary's conversations to primary
        conn.execute(
            "UPDATE conversations SET contact_id = ? WHERE contact_id = ?",
            (primary_id, secondary_id),
        )

        # Update primary with merged data
        conn.execute(
            """UPDATE contacts SET
               name = ?, company = ?, role = ?, notes = ?, linkedin_url = ?,
               tags = ?, first_contacted_at = ?, last_contacted_at = ?,
               total_touchpoints = ?, updated_at = ?
               WHERE id = ?""",
            (
                merged["name"], merged["company"], merged["role"],
                merged["notes"], merged["linkedin_url"],
                merged["tags_json"],
                merged["first_contacted_at"], merged["last_contacted_at"],
                merged["total_touchpoints"], now, primary_id,
            ),
        )

        # Archive secondary (soft delete)
        conn.execute(
            "UPDATE contacts SET status = 'archived', updated_at = ? WHERE id = ?",
            (now, secondary_id),
        )

        conn.commit()
        logger.info(f"Merged contact {secondary_id} → {primary_id}")

        return get_contact(primary_id, db_path=db_path)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Bulk dedup scan
# ---------------------------------------------------------------------------

def scan_all_duplicates(
    db_path: Path | None = None,
    min_confidence: float = 0.85,
) -> list[dict]:
    """Scan all active contacts for potential duplicates.

    Returns list of duplicate pairs (each pair appears once).
    """
    contacts = list_contacts(status="active", limit=5000, db_path=db_path)
    seen_pairs: set[frozenset] = set()
    results = []

    for contact in contacts:
        dupes = find_duplicates(contact["id"], db_path=db_path)
        for dupe in dupes:
            if dupe["confidence"] < min_confidence:
                continue
            pair = frozenset([contact["id"], dupe["contact_id"]])
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            results.append({
                "contact_a": {"id": contact["id"], "name": contact.get("name"), "email": contact.get("email")},
                "contact_b": {"id": dupe["contact_id"], "name": dupe["name"], "email": dupe["email"]},
                "confidence": dupe["confidence"],
                "reasons": dupe["reasons"],
            })

    results.sort(key=lambda x: x["confidence"], reverse=True)
    return results
