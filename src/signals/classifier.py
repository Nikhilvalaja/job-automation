"""Signal classifier — categorizes news text as hiring/layoff/noise.

Deterministic keyword-based classification.
No LLM required — fast, free, explainable.

Signal hierarchy (first match wins):
  layoff      > funding > acquisition > contract > expansion > leadership > product > noise
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ClassificationResult:
    signal_type: str        # one of SIGNAL_TYPES
    confidence: float       # 0.0 – 1.0
    matched_keywords: list[str]
    company: str            # extracted company name (best effort)
    amount: str             # funding/contract amount if found (e.g. "$200M")
    sector_tags: list[str] = None   # detected sector tags (e.g. ["healthcare", "cloud"])

    def __post_init__(self):
        if self.sector_tags is None:
            self.sector_tags = []


# ---------------------------------------------------------------------------
# Keyword dictionaries
# ---------------------------------------------------------------------------

_LAYOFF_KW = [
    "layoff", "laid off", "lay off", "reduction in force", "rif", "workforce reduction",
    "job cuts", "eliminating positions", "downsizing", "warn notice", "warn act",
    "restructuring", "headcount reduction", "staff cuts", "letting go",
]

_FUNDING_KW = [
    "raises", "raised", "funding", "series a", "series b", "series c", "series d",
    "seed round", "ipo", "pre-ipo", "investment", "venture capital", "vc funding",
    "secured funding", "led by", "closes", "valued at", "valuation", "unicorn",
    "backed by", "financed",
]

_ACQUISITION_KW = [
    "acquires", "acquired", "acquisition", "merger", "merges with", "buys",
    "purchased", "takeover", "deal worth", "agreed to acquire",
]

_CONTRACT_KW = [
    "awarded contract", "wins contract", "government contract", "federal contract",
    "dod contract", "pentagon", "usaf", "navy contract", "army contract",
    "indefinite delivery", "task order", "prime contractor", "subcontract",
    "contract award", "contract value",
]

_EXPANSION_KW = [
    "expanding", "expansion", "opens new", "new office", "new headquarters",
    "new facility", "growing team", "growing workforce", "hiring spree",
    "rapid growth", "scaling", "scale up", "headcount growth",
]

_LEADERSHIP_KW = [
    "appoints", "appointed", "names new", "hires", "joins as", "promoted to",
    "new cto", "new ceo", "new cpo", "new vp", "new head of", "new chief",
    "executive hire", "c-suite", "leadership team",
]

_PRODUCT_KW = [
    "launches", "launch", "releases", "unveils", "announces", "new product",
    "new platform", "new service", "generally available", "ga release",
    "major release", "version 2", "platform launch",
]

# Amount pattern: $100M, $1.2B, $500K, etc.
_AMOUNT_RE = re.compile(r"\$[\d,.]+\s*[KMBT](?:illion|illions?)?", re.IGNORECASE)

# Ordered list of (signal_type, keyword_list)
_CLASSIFIERS = [
    ("layoff",      _LAYOFF_KW),
    ("funding",     _FUNDING_KW),
    ("acquisition", _ACQUISITION_KW),
    ("contract",    _CONTRACT_KW),
    ("expansion",   _EXPANSION_KW),
    ("leadership",  _LEADERSHIP_KW),
    ("product",     _PRODUCT_KW),
]

# Sector tag detection — maps tag label → keywords
_SECTOR_TAG_KEYWORDS: dict[str, list[str]] = {
    "healthcare":       ["healthcare", "health tech", "ehr", "epic", "cerner", "hipaa",
                         "clinical", "hospital", "telemedicine", "digital health", "patient"],
    "cloud":            ["cloud", "aws", "gcp", "azure", "infrastructure", "kubernetes",
                         "cloud migration", "cloud platform"],
    "ai_ml":            ["artificial intelligence", "machine learning", "deep learning",
                         "llm", "generative ai", "ai platform", "nlp", "foundation model"],
    "data":             ["data platform", "data warehouse", "analytics", "databricks",
                         "snowflake", "spark", "dbt", "etl", "data engineering"],
    "fintech":          ["fintech", "payments", "banking", "financial services",
                         "cryptocurrency", "blockchain", "trading", "insurance tech"],
    "government":       ["federal", "dod", "pentagon", "government contract", "dhs",
                         "fedramp", "usaf", "navy", "army", "usaid"],
    "enterprise_saas":  ["saas", "enterprise software", "b2b", "crm", "erp",
                         "developer tools", "platform engineering"],
    "consumer":         ["consumer app", "mobile app", "social media", "e-commerce",
                         "marketplace", "retail tech"],
}


# ---------------------------------------------------------------------------
# Core classification
# ---------------------------------------------------------------------------

def classify_text(
    text: str,
    company_hint: str = "",
) -> ClassificationResult:
    """Classify a news headline or snippet into a signal type.

    Args:
        text: Headline + snippet text (combined)
        company_hint: If we already know the company from the source

    Returns:
        ClassificationResult with signal_type, confidence, matched_keywords
    """
    lower = text.lower()
    best_type = "noise"
    best_matches: list[str] = []
    best_conf = 0.0

    for sig_type, keywords in _CLASSIFIERS:
        matches = [kw for kw in keywords if kw in lower]
        if not matches:
            continue
        # Confidence: more keyword matches = higher confidence, capped at 0.95
        conf = min(0.95, 0.50 + len(matches) * 0.15)
        if conf > best_conf:
            best_conf = conf
            best_type = sig_type
            best_matches = matches

    # Extract amount (funding/contract amounts boost confidence)
    amount_match = _AMOUNT_RE.search(text)
    amount = amount_match.group(0) if amount_match else ""
    if amount and best_type in ("funding", "contract"):
        best_conf = min(0.95, best_conf + 0.10)

    # Extract company name (normalize it)
    raw_company = company_hint or _extract_company(text)
    from src.signals.normalizer import normalize_company
    company = normalize_company(raw_company) if raw_company else ""

    # Detect sector tags
    sector_tags = _detect_sector_tags(lower)

    return ClassificationResult(
        signal_type=best_type,
        confidence=best_conf,
        matched_keywords=best_matches,
        company=company,
        amount=amount,
        sector_tags=sector_tags,
    )


def _detect_sector_tags(lower_text: str) -> list[str]:
    """Return list of sector tags detected in text."""
    tags = []
    for tag, keywords in _SECTOR_TAG_KEYWORDS.items():
        if any(kw in lower_text for kw in keywords):
            tags.append(tag)
    return tags


def _extract_company(text: str) -> str:
    """Best-effort company extraction from news text.

    Looks for:
    - "CompanyName raises $..."
    - "CompanyName acquires..."
    - "CompanyName announces..."
    """
    # Common sentence patterns: first capitalized word(s) before an action keyword
    patterns = [
        r"^([A-Z][A-Za-z0-9\s&.,]+?)\s+(?:raises|acquires|launches|announces|appoints|expands|opens|hires)",
        r"^([A-Z][A-Za-z0-9\s&.,]+?)\s+(?:has|have)\s+(?:raised|acquired|announced)",
    ]
    for pat in patterns:
        m = re.match(pat, text.strip())
        if m:
            name = m.group(1).strip().rstrip(".,")
            if 2 <= len(name) <= 60:
                return name
    return ""


# ---------------------------------------------------------------------------
# Batch classification
# ---------------------------------------------------------------------------

def classify_feed_entries(
    entries: list[dict],
    company_hint: str = "",
) -> list[dict]:
    """Classify a list of RSS/API feed entries.

    Each entry should have 'title' and optionally 'summary'.
    Returns entries with 'signal_type', 'confidence', 'matched_keywords', 'amount' added.
    """
    results = []
    for entry in entries:
        text = f"{entry.get('title', '')} {entry.get('summary', '')}"
        r = classify_text(text, company_hint=company_hint)
        results.append({
            **entry,
            "signal_type": r.signal_type,
            "confidence": r.confidence,
            "matched_keywords": r.matched_keywords,
            "company": r.company or company_hint,
            "amount": r.amount,
            "sector_tags": r.sector_tags,
        })
    return results


def is_actionable(result: ClassificationResult, min_confidence: float = 0.50) -> bool:
    """Return True if the signal is worth saving (not noise, above confidence threshold)."""
    return result.signal_type != "noise" and result.confidence >= min_confidence
