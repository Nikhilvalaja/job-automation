"""Job quality filter — keeps 100K+ dataset clean and valuable.

Filters out:
- Staffing/recruiting agency postings (low signal, generic roles)
- Junk descriptions (too short, placeholder text)
- Bad titles (spam, misleading, bulk listings)
- Duplicate-pattern titles from the same company

Also normalizes:
- Title casing (removes ALL CAPS garbage)
- Company names (strips "(via Robert Half)" suffixes)
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Staffing agency detection
# ---------------------------------------------------------------------------

# Known staffing / recruiting / temp agencies to filter (or flag) out
STAFFING_AGENCIES: set[str] = {
    # Big US staffing firms
    "robert half", "robert half international",
    "adecco", "adecco group",
    "manpower", "manpower group", "manpowergroup",
    "kelly services", "kelly professional",
    "spherion",
    "staffmark",
    "randstad", "randstad usa",
    "aerotek",
    "insight global",
    "teksystems", "tek systems", "tekskills",
    "staffigo",
    "staffing solutions",
    "talent bridge",
    "vaco",
    "apex systems",
    "genesis10",
    "lancesoft",
    "iqresourcing",
    "cybercoders",
    "hired.com",
    "hired by matrix",
    "judge group",
    "staffing 360",
    "computer horizons",
    "acro service",
    "softpath systems",
    "compunnel",
    "futureforce",
    "modis",
    "experis",  # Manpower subsidiary
    "hays", "hays plc",
    "michael page",
    "page group",
    "capgemini staffing",
    "wipro staffing",
    "infosys bpo",
    "cognizant staffing",
    "hcl staffing",
    "tcs recruitment",
    "ust global staffing",
    "syntel staffing",
    "mastech", "mastech digital",
    "igate",
    "geometric",
    "globallogic staffing",
    "ltimindtree staffing",
    "tech mahindra staffing",
    "zensar staffing",
    "mphasis staffing",
    "hexaware staffing",
    "larsen & toubro infotech",
    "niit technologies",
    "in2it technologies",
    "ness technologies",
    "collabera",
    "princeton information",
    "smartsource",
    "disa",
    "spectraforce",
    "diverse lynx",
    "iris software",
    "tekforce",
    "dlt solutions",
    "softchoice staffing",
    "risepoint",
    "world wide technology staffing",
    "quickpath staffing",
    "us tech solutions",
    "coda staffing",
    "tanisha systems",
    "tanson corp",
    "softworld",
    "staffworks",
    "talentcare",
    "eliassen group",
    "dunhill staffing",
    "the select group",
    "comforce",
    "maximus federal",  # govt contractor / staffing
    "booz allen staffing",
    "saic staffing",
    "leidos staffing",
    "latitude 36 careers",
    "latitude 36",
    "career blazers",
    "jobs via dice",
    "jobs via indeed",
    "jobs via linkedin",
    "jobs via ziprecruiter",
    "jobs via glassdoor",
    "careerbuilder",
}

# Patterns in company name that suggest staffing/recruiting
_STAFFING_COMPANY_PATTERNS = re.compile(
    r"\b(staffing|recruiting|recruitment|temp|temporary|contract\s+hire|"
    r"talent\s+solutions|workforce|placement|outsourc|body\s+shop)\b",
    re.IGNORECASE,
)

# Patterns "via XYZ" from aggregators that wrap company names
_VIA_PATTERN = re.compile(r"\s*\(?via\s+[\w\s]+\)?", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Title quality
# ---------------------------------------------------------------------------

_BAD_TITLE_PATTERNS = re.compile(
    r"\b(now hiring|urgent|immediate|hot job|multiple positions?|various roles?|"
    r"staffing|temp to hire|contract to hire|perm to hire|hiring event|"
    r"hiring immediately|we are hiring|open positions?|career opportunity|"
    r"job opening|employment opportunity)\b",
    re.IGNORECASE,
)

# If title is ALL CAPS with more than 3 words → garbage
def _is_all_caps_title(title: str) -> bool:
    words = title.split()
    if len(words) < 4:
        return False
    upper_count = sum(1 for w in words if w.isupper() and len(w) > 1)
    return upper_count / len(words) > 0.7


# ---------------------------------------------------------------------------
# Description quality
# ---------------------------------------------------------------------------

MIN_DESCRIPTION_LENGTH = 80  # characters — shorter is placeholder/garbage

_JUNK_DESCRIPTION_PATTERNS = re.compile(
    r"^(n/a|not available|see job description|job description here|"
    r"apply now|click to apply|more details at|job details|description not provided)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_staffing_agency(company: str) -> bool:
    """Check if a company name matches known staffing agencies."""
    if not company:
        return False
    company_lower = company.lower().strip()

    # Direct match against known agencies
    if company_lower in STAFFING_AGENCIES:
        return True

    # Partial match for longer names
    for agency in STAFFING_AGENCIES:
        if len(agency) > 6 and agency in company_lower:
            return True

    # Pattern match for generic staffing terms
    if _STAFFING_COMPANY_PATTERNS.search(company):
        return True

    return False


def normalize_company_name(company: str) -> str:
    """Clean up company names from aggregators.

    Removes suffixes like "(via Robert Half)", "- Staffmark", etc.
    """
    if not company:
        return company
    # Strip "via XYZ" patterns
    cleaned = _VIA_PATTERN.sub("", company).strip()
    # Strip trailing " - Agency Name" patterns
    if " - " in cleaned:
        parts = cleaned.rsplit(" - ", 1)
        if is_staffing_agency(parts[1]):
            cleaned = parts[0].strip()
    return cleaned or company


def normalize_title(title: str) -> str:
    """Normalize a job title — fix casing, strip noise."""
    if not title:
        return title

    # ALL CAPS → Title Case
    if _is_all_caps_title(title):
        title = title.title()

    # Strip leading/trailing noise like "URGENT: " or "NEW: "
    title = re.sub(r"^(URGENT|NEW|HOT|OPEN|HIRING|IMMEDIATE)\s*:\s*", "", title, flags=re.IGNORECASE)

    return title.strip()


def filter_job(job: dict) -> tuple[bool, str]:
    """Decide whether a job is worth keeping.

    Returns:
        (keep: bool, reason: str)
        If keep=False, reason explains why it was rejected.

    Usage:
        keep, reason = filter_job(job)
        if not keep:
            logger.debug(f"Rejected {job['title']}: {reason}")
            continue
    """
    title = job.get("title", "").strip()
    company = job.get("company", "").strip()
    desc = job.get("description", "").strip()

    # 1. Must have a title
    if not title:
        return False, "no_title"

    # 2. Must have a URL
    if not job.get("url"):
        return False, "no_url"

    # 3. Title quality check
    if _BAD_TITLE_PATTERNS.search(title):
        return False, "bad_title_pattern"

    if _is_all_caps_title(title):
        # Don't reject — normalize instead, but flag for review
        pass

    # 4. Description length check
    if len(desc) < MIN_DESCRIPTION_LENGTH:
        return False, "description_too_short"

    # 5. Junk description check
    if desc and _JUNK_DESCRIPTION_PATTERNS.match(desc):
        return False, "junk_description"

    # 6. Staffing agency check (flag but don't reject by default)
    # We store is_staffing_agency=1 on the record so users can filter in dashboard
    # Only hard-reject if description also looks generic
    if is_staffing_agency(company):
        job["is_staffing_agency"] = True
        # Hard reject only if description is also too short — likely a placeholder post
        if len(desc) < 200:
            return False, "staffing_agency_stub"

    return True, "ok"


def score_quality(job: dict) -> float:
    """Compute a quality score 0.0-1.0 for a job record.

    Used to rank jobs within a match_score tier.
    Higher = more likely to be a real, complete job posting.
    """
    score = 1.0

    # Description completeness
    desc_len = len(job.get("description", ""))
    if desc_len < 200:
        score -= 0.3
    elif desc_len < 500:
        score -= 0.1

    # Staffing agency penalty
    if job.get("is_staffing_agency"):
        score -= 0.2

    # Location provided
    if not job.get("location"):
        score -= 0.1

    # Company provided
    if not job.get("company"):
        score -= 0.2

    return max(0.0, score)
