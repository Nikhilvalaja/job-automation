"""Referral closeness scorer.

Scores how close a CRM contact is to a target company.
Higher score = warmer intro path.

Scoring tiers:
  1.0  — you already spoke to someone at this company (touchpoint exists)
  0.85 — contact currently works there (company field matches)
  0.70 — contact previously worked there (detected via notes/tags)
  0.50 — same domain/industry as target (sector overlap)
  0.30 — same location or very similar industry
  0.20 — 2nd-degree (contact knows someone there — future; currently not supported)
  0.00 — no apparent connection
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ReferralScore:
    contact_id: str
    contact_name: str
    contact_email: str
    company: str              # contact's current company
    target_company: str
    score: float              # 0.0 – 1.0
    tier: str                 # "direct" | "former" | "industry" | "location" | "none"
    reasons: list[str] = field(default_factory=list)
    last_contacted: str = ""  # ISO date or ""
    touchpoint_count: int = 0
    suggested_ask: str = ""


# ---------------------------------------------------------------------------
# Company name matching
# ---------------------------------------------------------------------------

def _normalize(name: str) -> str:
    """Lowercase, strip common legal suffixes + punctuation."""
    name = name.lower().strip()
    name = re.sub(r",?\s*(?:inc\.?|llc\.?|corp\.?|ltd\.?|co\.?|plc\.?)\s*$", "", name)
    name = re.sub(r"[^\w\s]", "", name)
    return name.strip()


def _companies_match(a: str, b: str) -> bool:
    """Return True if two company names refer to the same company."""
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


# ---------------------------------------------------------------------------
# Core scoring
# ---------------------------------------------------------------------------

def score_contact_for_company(
    contact: dict,
    target_company: str,
    touchpoints: list[dict] | None = None,
) -> ReferralScore:
    """Score a single CRM contact's referral potential for target_company."""
    reasons: list[str] = []
    score = 0.0
    tier = "none"

    contact_id = contact.get("id", "")
    name = contact.get("name", "") or contact.get("email", "")
    email = contact.get("email", "")
    company = contact.get("company", "")
    tags: list[str] = contact.get("tags", []) if isinstance(contact.get("tags"), list) else []
    notes = (contact.get("notes", "") or "").lower()
    last_contacted = contact.get("last_contacted_at", "") or ""
    tp_count = len(touchpoints) if touchpoints else 0

    # Tier 1: spoke to someone at this company (touchpoint recorded)
    if tp_count > 0 and _companies_match(company, target_company):
        score = 1.0
        tier = "direct"
        reasons.append(f"spoke before ({tp_count} touchpoints)")

    # Tier 2: contact currently works there
    elif _companies_match(company, target_company):
        score = 0.85
        tier = "direct"
        reasons.append("currently works there")

    # Tier 3: former employee (notes or tags contain company name + past tense markers)
    elif _is_former_employee(notes, tags, target_company):
        score = 0.70
        tier = "former"
        reasons.append("former employee (detected in notes/tags)")

    # Tier 4: same industry/domain
    else:
        industry_boost = _industry_overlap(company, target_company, notes, tags)
        if industry_boost > 0:
            score = industry_boost
            tier = "industry"
            reasons.append("same industry/sector")

    # Recency bonus: if we've spoken recently, boost slightly (max +0.10)
    if last_contacted and score > 0:
        try:
            from datetime import datetime
            days_ago = (datetime.utcnow() - datetime.fromisoformat(last_contacted)).days
            if days_ago <= 30:
                bonus = 0.10
            elif days_ago <= 90:
                bonus = 0.05
            else:
                bonus = 0.0
            if bonus > 0:
                score = min(1.0, score + bonus)
                reasons.append(f"recent contact ({days_ago}d ago)")
        except Exception:
            pass

    suggested_ask = _build_ask(tier, name, target_company)

    return ReferralScore(
        contact_id=contact_id,
        contact_name=name,
        contact_email=email,
        company=company,
        target_company=target_company,
        score=round(score, 3),
        tier=tier,
        reasons=reasons,
        last_contacted=last_contacted[:10] if last_contacted else "",
        touchpoint_count=tp_count,
        suggested_ask=suggested_ask,
    )


def _is_former_employee(notes: str, tags: list[str], target_company: str) -> bool:
    """Detect 'ex-Company' or 'formerly Company' patterns."""
    normalized = _normalize(target_company)
    # Check tags for "ex-X" or "alumni" patterns
    for tag in tags:
        t = tag.lower()
        if normalized in t and ("ex" in t or "former" in t or "alumni" in t or "prev" in t):
            return True
    # Check notes
    patterns = [
        rf"ex[-\s]{re.escape(normalized)}",
        rf"former(?:ly)?(?:\s+at)?\s+{re.escape(normalized)}",
        rf"previously(?:\s+at)?\s+{re.escape(normalized)}",
        rf"{re.escape(normalized)}\s+alumni",
        rf"worked\s+at\s+{re.escape(normalized)}",
    ]
    for pat in patterns:
        if re.search(pat, notes, re.IGNORECASE):
            return True
    return False


def _industry_overlap(contact_company: str, target_company: str, notes: str, tags: list[str]) -> float:
    """Return a score 0.0–0.35 based on shared industry signals."""
    _TECH_TERMS = {"tech", "software", "saas", "cloud", "ai", "data", "fintech", "startup", "platform"}
    combined = f"{contact_company} {notes} {' '.join(tags)}".lower()
    target_lower = target_company.lower()

    # Both are tech companies (rough heuristic)
    contact_is_tech = any(t in combined for t in _TECH_TERMS)
    target_is_tech = any(t in target_lower for t in _TECH_TERMS)

    if contact_is_tech and target_is_tech:
        return 0.35
    if contact_is_tech or target_is_tech:
        return 0.20
    return 0.0


def _build_ask(tier: str, name: str, company: str) -> str:
    first = name.split()[0] if name else "there"
    if tier == "direct":
        return f"Hi {first}, I'm exploring roles at {company} — would you be open to a brief chat or passing along my profile?"
    if tier == "former":
        return f"Hi {first}, I saw you worked at {company} — would you have any insights or know who to connect with?"
    if tier == "industry":
        return f"Hi {first}, we're both in similar spaces — would you happen to have any contacts at {company}?"
    return f"Hi {first}, do you know anyone at {company} who might be open to a chat?"
