"""Job matching preferences and scoring engine.

Scores discovered jobs against user preferences to determine relevance.
Uses keyword matching with weighted scoring (title > description).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class JobPreferences:
    """User's job search preferences."""
    keywords: list[str] = field(default_factory=list)
    excluded_keywords: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    min_match_score: float = 0.3

    @classmethod
    def from_config(cls) -> "JobPreferences":
        """Load preferences from environment/config."""
        settings = get_settings()

        keywords = [k.strip().lower() for k in settings.discovery_keywords.split(",") if k.strip()]
        excluded = [k.strip().lower() for k in settings.discovery_excluded_keywords.split(",") if k.strip()]
        locations = [k.strip().lower() for k in settings.discovery_locations.split(",") if k.strip()]

        return cls(
            keywords=keywords,
            excluded_keywords=excluded,
            locations=locations,
        )


def score_job(
    title: str,
    description: str,
    company: str,
    location: str,
    preferences: JobPreferences,
) -> float:
    """Score a job against user preferences.

    Returns a score from 0.0 (no match) to 1.0 (perfect match).
    Returns -1.0 if job contains excluded keywords (auto-reject).

    Scoring weights:
    - Title keyword match: 0.4 per keyword (max 0.8)
    - Description keyword match: 0.15 per keyword (max 0.6)
    - Location match: 0.2 bonus
    - Excluded keyword: -1.0 (instant reject)
    """
    if not preferences.keywords:
        # No preferences configured — accept everything with a neutral score
        return 0.5

    title_lower = title.lower()
    desc_lower = description.lower()
    company_lower = company.lower()
    location_lower = location.lower()

    # Check exclusions first
    all_text = f"{title_lower} {desc_lower} {company_lower}"
    for excluded in preferences.excluded_keywords:
        if excluded in title_lower:
            return -1.0  # Hard reject if excluded keyword in title

    score = 0.0

    # Title keyword matches (high weight — 0.4 each, max 0.8)
    title_matches = 0
    for kw in preferences.keywords:
        if kw in title_lower:
            title_matches += 1
    score += min(title_matches * 0.4, 0.8)

    # Description keyword matches (lower weight — 0.15 each, max 0.6)
    desc_matches = 0
    for kw in preferences.keywords:
        if kw in desc_lower:
            desc_matches += 1
    score += min(desc_matches * 0.15, 0.6)

    # Location match bonus
    if preferences.locations:
        for loc in preferences.locations:
            if loc in location_lower or loc in desc_lower or loc in title_lower:
                score += 0.2
                break

    # Cap at 1.0
    return min(score, 1.0)
