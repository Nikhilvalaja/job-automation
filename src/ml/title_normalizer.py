"""Job title normalization for consistent matching.

Normalizes titles like:
- "Sr. Data Engineer II" -> canonical: "data_engineer", level: "senior"
- "Staff ML Eng" -> canonical: "ml_engineer", level: "staff"
- "Junior Backend Developer" -> canonical: "backend", level: "entry"

Uses deterministic rules only — no LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class NormalizedTitle:
    """Result of title normalization."""
    raw: str
    canonical: str          # e.g. "data_engineer", "backend", "ml_engineer"
    seniority: str          # e.g. "entry", "mid", "senior", "staff", "lead"
    clean: str              # lowered, stripped of level/numeral suffixes


# ---------------------------------------------------------------------------
# Level Detection
# ---------------------------------------------------------------------------

_LEVEL_PATTERNS: list[tuple[str, list[str]]] = [
    ("principal", ["principal", "distinguished", "fellow"]),
    ("staff", ["staff"]),
    ("director", ["director", "vp", "vice president"]),
    ("lead", ["lead", "team lead", "tech lead", "engineering lead"]),
    ("senior", ["senior", "sr.", "sr ", "ssr", "senior level"]),
    ("entry", ["junior", "jr.", "jr ", "entry", "associate", "graduate",
               "new grad", "early career", "intern", "internship"]),
]


def _detect_seniority(title_lower: str) -> str:
    """Detect seniority level from title text."""
    for level, keywords in _LEVEL_PATTERNS:
        for kw in keywords:
            if kw in title_lower:
                return level
    return "mid"


# ---------------------------------------------------------------------------
# Role Canonical Mapping
# ---------------------------------------------------------------------------

_ROLE_RULES: list[tuple[str, list[str]]] = [
    ("data_scientist", [
        "data scientist", "data science", "data analyst", "analytics engineer",
        "business intelligence", "bi analyst", "bi engineer",
    ]),
    ("data_engineer", [
        "data engineer", "data platform", "data infrastructure",
        "etl developer", "etl engineer", "analytics engineer",
    ]),
    ("ml_engineer", [
        "machine learning", "ml engineer", "ml ops", "mlops",
        "deep learning", "ai engineer", "ai/ml", "ml/ai",
        "applied scientist", "research engineer", "research scientist",
    ]),
    ("backend", [
        "backend", "back-end", "back end", "server-side",
        "api developer", "api engineer", "platform engineer",
        "systems engineer", "infrastructure engineer",
    ]),
    ("frontend", [
        "frontend", "front-end", "front end", "ui developer",
        "ui engineer", "web developer", "react developer",
    ]),
    ("fullstack", [
        "full stack", "fullstack", "full-stack",
    ]),
    ("devops", [
        "devops", "dev ops", "sre", "site reliability",
        "cloud engineer", "cloud architect", "infrastructure",
        "platform engineer",
    ]),
    ("mobile", [
        "ios developer", "ios engineer", "android developer",
        "android engineer", "mobile developer", "mobile engineer",
        "react native", "flutter developer",
    ]),
    ("security", [
        "security engineer", "cybersecurity", "infosec",
        "application security", "appsec", "security analyst",
        "penetration", "devsecops",
    ]),
    ("qa", [
        "qa engineer", "quality assurance", "test engineer",
        "sdet", "automation engineer", "quality engineer",
    ]),
    ("product_manager", [
        "product manager", "product owner", "program manager",
        "technical program manager", "tpm",
    ]),
    ("designer", [
        "ux designer", "ui designer", "product designer",
        "ux researcher", "interaction designer",
    ]),
    ("solutions_engineer", [
        "solutions engineer", "solutions architect",
        "sales engineer", "pre-sales", "customer engineer",
    ]),
    ("engineering_manager", [
        "engineering manager", "em", "eng manager",
        "development manager", "software manager",
    ]),
]

# Numeral suffixes to strip: I, II, III, IV, V, 1, 2, 3
_NUMERAL_PATTERN = re.compile(
    r"\s*(?:(?:i{1,3}|iv|v|vi{0,3})|[1-5])\s*$",
    re.IGNORECASE,
)

# Level words to strip for clean title
_LEVEL_STRIP = re.compile(
    r"\b(?:senior|sr\.?|junior|jr\.?|lead|staff|principal|"
    r"distinguished|associate|entry[- ]level|intern|internship)\b",
    re.IGNORECASE,
)


def _detect_role(title_lower: str) -> str:
    """Detect canonical role from title text."""
    for role, keywords in _ROLE_RULES:
        for kw in keywords:
            if kw in title_lower:
                return role
    # Default: check for generic "software engineer" / "developer"
    if any(w in title_lower for w in ["software engineer", "software developer",
                                       "developer", "engineer", "programmer"]):
        return "software_engineer"
    return "other"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize_title(title: str) -> NormalizedTitle:
    """Normalize a job title into canonical form + seniority level.

    >>> r = normalize_title("Sr. Data Engineer II")
    >>> r.canonical
    'data_engineer'
    >>> r.seniority
    'senior'

    >>> r = normalize_title("Junior Backend Developer")
    >>> r.canonical
    'backend'
    >>> r.seniority
    'entry'
    """
    if not title:
        return NormalizedTitle(raw=title, canonical="other", seniority="mid", clean="")

    lower = title.strip().lower()

    # Detect seniority
    seniority = _detect_seniority(lower)

    # Detect role
    canonical = _detect_role(lower)

    # Clean title: strip level words, numerals, extra whitespace
    clean = _LEVEL_STRIP.sub("", lower)
    clean = _NUMERAL_PATTERN.sub("", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    # Strip common noise: "(Remote)", "[US]", etc.
    clean = re.sub(r"\s*[\(\[\{].*?[\)\]\}]\s*", " ", clean).strip()
    clean = re.sub(r"\s*[-–—]\s*$", "", clean).strip()

    return NormalizedTitle(
        raw=title,
        canonical=canonical,
        seniority=seniority,
        clean=clean,
    )


def titles_match(title_a: str, title_b: str) -> float:
    """Compute similarity between two job titles (0.0 - 1.0).

    Uses canonical role matching + seniority alignment.
    """
    norm_a = normalize_title(title_a)
    norm_b = normalize_title(title_b)

    score = 0.0

    # Same canonical role: 0.6
    if norm_a.canonical == norm_b.canonical:
        score += 0.6
    # Related roles: 0.3
    elif _roles_related(norm_a.canonical, norm_b.canonical):
        score += 0.3

    # Same seniority: 0.3
    if norm_a.seniority == norm_b.seniority:
        score += 0.3
    # Adjacent seniority: 0.15
    elif _seniority_adjacent(norm_a.seniority, norm_b.seniority):
        score += 0.15

    # Exact clean match bonus: 0.1
    if norm_a.clean == norm_b.clean and norm_a.clean:
        score += 0.1

    return min(score, 1.0)


_SENIORITY_ORDER = ["entry", "mid", "senior", "staff", "lead", "principal", "director"]

_RELATED_ROLES: list[set[str]] = [
    {"backend", "fullstack", "software_engineer"},
    {"frontend", "fullstack", "software_engineer"},
    {"data_engineer", "data_scientist", "ml_engineer"},
    {"devops", "backend", "software_engineer"},
    {"mobile", "frontend", "software_engineer"},
]


def _seniority_adjacent(a: str, b: str) -> bool:
    """Check if two seniority levels are one step apart."""
    try:
        idx_a = _SENIORITY_ORDER.index(a)
        idx_b = _SENIORITY_ORDER.index(b)
        return abs(idx_a - idx_b) == 1
    except ValueError:
        return False


def _roles_related(a: str, b: str) -> bool:
    """Check if two roles are in the same related group."""
    for group in _RELATED_ROLES:
        if a in group and b in group:
            return True
    return False
