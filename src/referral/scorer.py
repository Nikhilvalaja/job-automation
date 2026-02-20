"""Referral closeness scorer — v2.

Final score formula:
    final_score = closeness_score * role_alignment_score * signal_multiplier * hiring_window_multiplier
    (capped at 1.0, 0.0 if fatigue_blocked)

Closeness tiers:
  1.0  — spoke before (touchpoint exists at target company)
  0.85 — currently works there
  0.70 — former employee (detected via notes/tags)
  0.35 — same industry/tech sector
  0.00 — no connection

Role alignment multipliers:
  1.0  — same function (engineering→engineering, data→data)
  0.75 — related (devops↔engineering, data↔ml)
  0.50 — cross-functional (still useful referral)
  0.80 — leadership (VP/Director at any company — broadly valuable)
  0.40 — unrelated function

Signal multipliers:
  1.30 — company hiring_score >= 0.80 (hot)
  1.15 — hiring_score >= 0.65 (warm signal)
  1.00 — neutral
  0.50 — hiring_score < 0.30 (layoff risk)

Hiring window multipliers:
  1.20 — warm (0-30d since funding)
  1.30 — peak (30-90d since funding)
  0.85 — cooling (90d+)
  1.00 — unknown

Fatigue rules:
  Block if messaged within last 14 days
  Block if 2+ outbound with no reply in last 30 days
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class ReferralScore:
    contact_id: str
    contact_name: str
    contact_email: str
    company: str              # contact's current company
    contact_role: str         # contact's role/title
    target_company: str
    target_job_title: str     # job we're applying for

    # Component scores
    closeness_score: float    # 0.0 – 1.0 (tier-based)
    role_alignment_score: float  # 0.0 – 1.0
    signal_multiplier: float  # 0.5 – 1.3
    hiring_window_multiplier: float  # 0.85 – 1.3
    final_score: float        # closeness * alignment * signal * window, capped 1.0

    tier: str                 # "direct" | "former" | "industry" | "none"
    reasons: list[str] = field(default_factory=list)
    last_contacted: str = ""  # ISO date or ""
    touchpoint_count: int = 0

    # Fatigue
    fatigue_blocked: bool = False
    fatigue_reason: str = ""

    # Context
    hiring_window: str = "unknown"
    signal_context: str = ""  # e.g. "raised $200M 42d ago"

    suggested_ask: str = ""

    # Convenience alias so callers can use .score
    @property
    def score(self) -> float:
        return self.final_score


# ---------------------------------------------------------------------------
# Company name matching
# ---------------------------------------------------------------------------

def _normalize(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r",?\s*(?:inc\.?|llc\.?|corp\.?|ltd\.?|co\.?|plc\.?)\s*$", "", name)
    name = re.sub(r"[^\w\s]", "", name)
    return name.strip()


def _companies_match(a: str, b: str) -> bool:
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


# ---------------------------------------------------------------------------
# Role alignment
# ---------------------------------------------------------------------------

_ROLE_CATEGORIES: dict[str, set[str]] = {
    # More specific categories first — checked in order, first match wins
    "devops": {
        "devops", "sre", "infrastructure", "site reliability", "reliability engineering",
        "devsecops", "kubernetes", "platform engineer",
    },
    "data": {
        "data scientist", "data engineer", "data analyst", "machine learning",
        "ml engineer", "ai engineer", "nlp", "deep learning", "bi engineer",
        "business intelligence", "analytics engineer",
    },
    "engineering": {
        "software engineer", "backend engineer", "frontend engineer", "fullstack",
        "full stack", "swe", "developer", "coder", "programmer", "web developer",
        "software developer",
    },
    "product": {
        "product", "pm", "product manager", "program manager", "tpm",
    },
    "design": {
        "design", "designer", "ux", "ui", "product design",
    },
    "healthcare": {
        "clinical", "health", "medical", "nurse", "doctor", "pharmacy",
        "ehr", "epic", "cerner", "clinical informatics",
    },
    "finance": {
        "finance", "accounting", "financial", "controller", "cfo", "cpa",
    },
    "sales": {
        "sales", "account executive", "ae", "bdr", "sdr", "account manager",
    },
    "leadership": {
        "vp", "director", "cto", "ceo", "cpo", "chief", "head of",
        "vice president", "managing director",
    },
}

# Compatibility matrix: (cat_a, cat_b) → multiplier
# Only need to define non-1.0 pairs; missing = 0.40
_ROLE_COMPAT: dict[tuple[str, str], float] = {
    ("engineering", "engineering"): 1.00,
    ("data", "data"):               1.00,
    ("devops", "devops"):           1.00,
    ("product", "product"):         1.00,
    ("design", "design"):           1.00,
    ("healthcare", "healthcare"):   1.00,
    ("devops", "engineering"):      0.75,
    ("engineering", "devops"):      0.75,
    ("data", "engineering"):        0.70,
    ("engineering", "data"):        0.70,
    ("data", "devops"):             0.60,
    ("devops", "data"):             0.60,
}
# Leadership contacts are broadly valuable regardless of target function
_LEADERSHIP_MULTIPLIER = 0.80
_DEFAULT_COMPAT = 0.40


def _categorize_role(role: str) -> str:
    if not role:
        return "unknown"
    r = role.lower()
    for category, keywords in _ROLE_CATEGORIES.items():
        if any(kw in r for kw in keywords):
            return category
    return "unknown"


def compute_role_alignment(contact_role: str, target_job_title: str) -> float:
    """Return 0.0–1.0 multiplier for how well contact's role aligns with target job."""
    if not contact_role or not target_job_title:
        return 0.60  # unknown — assume moderate alignment

    cat_contact = _categorize_role(contact_role)
    cat_target = _categorize_role(target_job_title)

    if cat_contact == "leadership":
        return _LEADERSHIP_MULTIPLIER
    if cat_contact == "unknown" or cat_target == "unknown":
        return 0.55  # can't determine — partial credit

    return _ROLE_COMPAT.get(
        (cat_contact, cat_target),
        _ROLE_COMPAT.get((cat_target, cat_contact), _DEFAULT_COMPAT),
    )


# ---------------------------------------------------------------------------
# Signal boost
# ---------------------------------------------------------------------------

def compute_signal_multiplier(target_company: str) -> tuple[float, str]:
    """Return (multiplier, context_string) from hiring signals DB."""
    try:
        from src.signals.database import get_company_score
        score_row = get_company_score(target_company)
        if not score_row:
            return 1.0, ""
        hiring_score = score_row.get("hiring_score", 0.5)
        trend = score_row.get("trend", "stable")

        if hiring_score < 0.30:
            return 0.50, f"layoff risk (signal score {hiring_score:.0%})"
        if hiring_score >= 0.80:
            context = f"hot hiring signal ({hiring_score:.0%}"
            if trend == "up":
                context += ", trending up"
            return 1.30, context + ")"
        if hiring_score >= 0.65:
            return 1.15, f"positive signal ({hiring_score:.0%})"
        return 1.00, ""
    except Exception:
        return 1.0, ""


# ---------------------------------------------------------------------------
# Hiring window timing
# ---------------------------------------------------------------------------

def compute_hiring_window_multiplier(target_company: str) -> tuple[float, str]:
    """Return (multiplier, window_label) from signals DB funding date."""
    try:
        from src.signals.database import get_company_score
        from src.signals.scorer import compute_hiring_window
        score_row = get_company_score(target_company)
        if not score_row:
            return 1.0, "unknown"
        window = compute_hiring_window(score_row.get("last_funding_at"))
        multipliers = {
            "warm":    (1.20, "warm"),
            "peak":    (1.30, "peak — best time to reach out"),
            "cooling": (0.85, "cooling"),
            "unknown": (1.00, "unknown"),
        }
        return multipliers.get(window, (1.0, "unknown"))
    except Exception:
        return 1.0, "unknown"


# ---------------------------------------------------------------------------
# Referral fatigue
# ---------------------------------------------------------------------------

_FATIGUE_COOLDOWN_DAYS = 14
_FATIGUE_MAX_UNANSWERED = 2
_FATIGUE_UNANSWERED_WINDOW_DAYS = 30


def check_referral_fatigue(
    touchpoints: list[dict] | None,
    last_contacted: str,
) -> tuple[bool, str]:
    """Return (blocked, reason). True means do NOT recommend right now."""
    if not touchpoints:
        return False, ""

    now = datetime.utcnow()
    cutoff_14d = (now - timedelta(days=_FATIGUE_COOLDOWN_DAYS)).isoformat()
    cutoff_30d = (now - timedelta(days=_FATIGUE_UNANSWERED_WINDOW_DAYS)).isoformat()

    # Rule 1: any message in last 14 days
    recent = [tp for tp in touchpoints if (tp.get("created_at") or "") >= cutoff_14d]
    if recent:
        days_ago = min(
            (now - datetime.fromisoformat(tp["created_at"])).days
            for tp in recent
            if tp.get("created_at")
        )
        return True, f"messaged {days_ago}d ago (cooldown {_FATIGUE_COOLDOWN_DAYS}d)"

    # Rule 2: 2+ outbound messages in last 30 days with no inbound reply
    last_30 = [tp for tp in touchpoints if (tp.get("created_at") or "") >= cutoff_30d]
    outbound = [tp for tp in last_30 if tp.get("direction") in ("outbound", "sent", "")]
    inbound  = [tp for tp in last_30 if tp.get("direction") in ("inbound", "received")]
    if len(outbound) >= _FATIGUE_MAX_UNANSWERED and not inbound:
        return True, f"{len(outbound)} unanswered messages in last 30 days"

    return False, ""


# ---------------------------------------------------------------------------
# Core scoring
# ---------------------------------------------------------------------------

def score_contact_for_company(
    contact: dict,
    target_company: str,
    target_job_title: str = "",
    touchpoints: list[dict] | None = None,
    use_signals: bool = True,
) -> ReferralScore:
    """Score a single CRM contact's referral potential.

    Args:
        contact: CRM contact dict
        target_company: Company you're applying to
        target_job_title: Role you're applying for (used for role alignment)
        touchpoints: Contact's touchpoint history
        use_signals: Whether to query signals DB for boost (default True)
    """
    reasons: list[str] = []
    closeness = 0.0
    tier = "none"

    contact_id = contact.get("id", "")
    name = contact.get("name", "") or contact.get("email", "")
    email = contact.get("email", "")
    company = contact.get("company", "")
    contact_role = contact.get("role", "") or ""
    tags: list[str] = contact.get("tags", []) if isinstance(contact.get("tags"), list) else []
    notes = (contact.get("notes", "") or "").lower()
    last_contacted = contact.get("last_contacted_at", "") or ""
    tp_count = len(touchpoints) if touchpoints else 0

    # ---- Closeness tier ----
    if tp_count > 0 and _companies_match(company, target_company):
        closeness = 1.0
        tier = "direct"
        reasons.append(f"spoke before ({tp_count} touchpoints)")
    elif _companies_match(company, target_company):
        closeness = 0.85
        tier = "direct"
        reasons.append("currently works there")
    elif _is_former_employee(notes, tags, target_company):
        closeness = 0.70
        tier = "former"
        reasons.append("former employee (notes/tags)")
    else:
        overlap = _industry_overlap(company, target_company, notes, tags)
        if overlap > 0:
            closeness = overlap
            tier = "industry"
            reasons.append("same industry/sector")

    # Recency bonus (max +0.10)
    if last_contacted and closeness > 0:
        try:
            days_ago = (datetime.utcnow() - datetime.fromisoformat(last_contacted)).days
            if days_ago <= 30:
                closeness = min(1.0, closeness + 0.10)
                reasons.append(f"recent contact ({days_ago}d ago)")
            elif days_ago <= 90:
                closeness = min(1.0, closeness + 0.05)
        except Exception:
            pass

    # ---- Role alignment ----
    role_alignment = compute_role_alignment(contact_role, target_job_title)
    if role_alignment < 0.50 and tier not in ("direct", "former"):
        reasons.append(f"weak role alignment ({contact_role!r} → {target_job_title!r})")
    elif role_alignment >= 0.90:
        reasons.append(f"same function ({_categorize_role(contact_role)})")

    # ---- Signal multiplier ----
    signal_mult, signal_ctx = (compute_signal_multiplier(target_company)
                                if use_signals else (1.0, ""))
    if signal_ctx:
        reasons.append(signal_ctx)

    # ---- Hiring window ----
    window_mult, hiring_window = (compute_hiring_window_multiplier(target_company)
                                   if use_signals else (1.0, "unknown"))
    if hiring_window not in ("unknown", ""):
        reasons.append(f"hiring window: {hiring_window}")

    # ---- Fatigue check ----
    fatigue_blocked, fatigue_reason = check_referral_fatigue(touchpoints, last_contacted)

    # ---- Final score ----
    raw = closeness * role_alignment * signal_mult * window_mult
    final = round(min(1.0, max(0.0, raw)), 3)
    if fatigue_blocked:
        final = 0.0  # still computed but will be filtered by finder

    suggested_ask = _build_ask(
        tier=tier,
        name=name,
        company=target_company,
        contact_role=contact_role,
        target_job_title=target_job_title,
        signal_context=signal_ctx,
        hiring_window=hiring_window,
    )

    return ReferralScore(
        contact_id=contact_id,
        contact_name=name,
        contact_email=email,
        company=company,
        contact_role=contact_role,
        target_company=target_company,
        target_job_title=target_job_title,
        closeness_score=round(closeness, 3),
        role_alignment_score=round(role_alignment, 3),
        signal_multiplier=round(signal_mult, 3),
        hiring_window_multiplier=round(window_mult, 3),
        final_score=final,
        tier=tier,
        reasons=reasons,
        last_contacted=last_contacted[:10] if last_contacted else "",
        touchpoint_count=tp_count,
        fatigue_blocked=fatigue_blocked,
        fatigue_reason=fatigue_reason,
        hiring_window=hiring_window,
        signal_context=signal_ctx,
        suggested_ask=suggested_ask,
    )


# ---------------------------------------------------------------------------
# Former employee detection
# ---------------------------------------------------------------------------

def _is_former_employee(notes: str, tags: list[str], target_company: str) -> bool:
    normalized = _normalize(target_company)
    for tag in tags:
        t = tag.lower()
        if normalized in t and ("ex" in t or "former" in t or "alumni" in t or "prev" in t):
            return True
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
    _TECH_TERMS = {"tech", "software", "saas", "cloud", "ai", "data", "fintech", "startup", "platform"}
    combined = f"{contact_company} {notes} {' '.join(tags)}".lower()
    target_lower = target_company.lower()
    contact_is_tech = any(t in combined for t in _TECH_TERMS)
    target_is_tech = any(t in target_lower for t in _TECH_TERMS)
    if contact_is_tech and target_is_tech:
        return 0.35
    if contact_is_tech or target_is_tech:
        return 0.20
    return 0.0


# ---------------------------------------------------------------------------
# Context-aware suggested ask
# ---------------------------------------------------------------------------

def _build_ask(
    tier: str,
    name: str,
    company: str,
    contact_role: str = "",
    target_job_title: str = "",
    signal_context: str = "",
    hiring_window: str = "unknown",
) -> str:
    first = name.split()[0] if name else "there"
    role_str = f" {target_job_title}" if target_job_title else ""
    their_role = f" (I see you're in {contact_role})" if contact_role else ""

    # Signal timing line
    timing_line = ""
    if hiring_window == "peak":
        timing_line = " I noticed they seem to be actively hiring right now."
    elif hiring_window == "warm":
        timing_line = " Timing seems good — they've been growing recently."
    elif signal_context and "layoff" not in signal_context.lower():
        timing_line = f" ({signal_context})"

    if tier == "direct":
        if contact_role and target_job_title:
            cat_contact = _categorize_role(contact_role)
            cat_target = _categorize_role(target_job_title)
            if cat_contact == cat_target:
                return (
                    f"Hi {first}, since we've spoken before and you're in {contact_role} at {company} — "
                    f"I'm exploring{role_str} roles there.{timing_line} "
                    f"Would you be open to a quick chat or passing along my profile to the hiring team?"
                )
        return (
            f"Hi {first}, since we've connected before —{timing_line} "
            f"I'm exploring{role_str} opportunities at {company}. "
            f"Would you be open to a brief chat or sharing my profile?"
        )

    if tier == "former":
        return (
            f"Hi {first},{their_role} — I saw you worked at {company} before.{timing_line} "
            f"I'm applying for{role_str} roles there and would love any insider perspective "
            f"or a referral if you're still connected. Would you have 10 minutes?"
        )

    if tier == "industry":
        return (
            f"Hi {first},{their_role} — we're both in the tech space.{timing_line} "
            f"I'm targeting{role_str} roles at {company} and was wondering if you happen to "
            f"know anyone there who might be open to a quick chat?"
        )

    return (
        f"Hi {first}, do you happen to know anyone at {company}?{timing_line} "
        f"I'm exploring{role_str} opportunities there and any intro would mean a lot."
    )
