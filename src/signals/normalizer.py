"""Company name normalization — canonical IDs.

Handles:
  "Stripe Inc."           → "Stripe"
  "Meta Platforms, Inc."  → "Meta"
  "Alphabet Inc."         → "Google"
  "stripe"                → "Stripe"

Used everywhere signals are saved so scores don't fragment across name variants.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

# Strip common legal suffixes
_LEGAL_SUFFIX_RE = re.compile(
    r",?\s*(?:Inc\.?|LLC\.?|L\.L\.C\.?|Corp\.?|Ltd\.?|Co\.?|L\.P\.?|LP|PLC|"
    r"S\.A\.?|N\.V\.?|B\.V\.?|GmbH|AG|SE|Limited|Corporation|"
    r"Incorporated|Company|Partners|Group|Holdings?|Technologies?|"
    r"Solutions?|Systems?|Services?|Enterprises?|International)\s*$",
    re.IGNORECASE,
)

# Known aliases → canonical name
_ALIASES: dict[str, str] = {
    # Meta
    "meta platforms": "Meta",
    "facebook": "Meta",
    "meta platforms inc": "Meta",
    # Google
    "alphabet": "Google",
    "alphabet inc": "Google",
    "google llc": "Google",
    "google inc": "Google",
    # Amazon
    "amazon web services": "AWS",
    "aws": "AWS",
    "amazon.com": "Amazon",
    # Microsoft
    "microsoft corporation": "Microsoft",
    # Twitter / X
    "x corp": "X",
    "twitter": "X",
    "twitter inc": "X",
    # Apple
    "apple inc": "Apple",
    # Salesforce
    "salesforce.com": "Salesforce",
    "salesforce inc": "Salesforce",
    # Netflix
    "netflix inc": "Netflix",
    # Uber
    "uber technologies": "Uber",
    # Lyft
    "lyft inc": "Lyft",
    # Airbnb
    "airbnb inc": "Airbnb",
    # Stripe
    "stripe inc": "Stripe",
    # OpenAI
    "openai inc": "OpenAI",
    # Anthropic
    "anthropic pbc": "Anthropic",
    # Databricks
    "databricks inc": "Databricks",
    # Snowflake
    "snowflake inc": "Snowflake",
    # HubSpot
    "hubspot inc": "HubSpot",
    # ServiceNow
    "servicenow inc": "ServiceNow",
    # Workday
    "workday inc": "Workday",
    # Palantir
    "palantir technologies": "Palantir",
    # Epic Systems
    "epic systems corporation": "Epic Systems",
    "epic systems": "Epic Systems",
}


def normalize_company(name: str) -> str:
    """Return canonical company name.

    1. Check alias table (exact match after lowercase)
    2. Strip legal suffixes
    3. Strip trailing punctuation/whitespace
    4. Check alias table again
    5. Title-case result
    """
    if not name:
        return ""

    stripped = name.strip()

    # Alias check (pre-normalization)
    lower = stripped.lower()
    if lower in _ALIASES:
        return _ALIASES[lower]

    # Strip legal suffix
    cleaned = _LEGAL_SUFFIX_RE.sub("", stripped).strip().strip(".,;: ")

    # Alias check (post-normalization)
    lower2 = cleaned.lower()
    if lower2 in _ALIASES:
        return _ALIASES[lower2]

    # Return cleaned name (preserve original casing if mixed, else title-case)
    return cleaned if cleaned else name


def companies_are_same(name_a: str, name_b: str) -> bool:
    """Check if two company names refer to the same company."""
    return normalize_company(name_a).lower() == normalize_company(name_b).lower()


def company_similarity(name_a: str, name_b: str) -> float:
    """Fuzzy similarity between two company names (after normalization)."""
    a = normalize_company(name_a).lower()
    b = normalize_company(name_b).lower()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def normalize_company_list(names: list[str]) -> dict[str, str]:
    """Normalize a list of company names, return {original: canonical} map."""
    return {name: normalize_company(name) for name in names}
