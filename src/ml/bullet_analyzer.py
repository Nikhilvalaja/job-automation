"""Resume bullet point analyzer.

Extracts structured data from individual resume bullet points:
- Word count
- Tools/technologies mentioned
- Quantified metrics (numbers, percentages, dollar amounts)
- Action verbs
- Strength assessment

100% deterministic — no LLM calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.ml.skill_taxonomy import extract_skills


@dataclass
class AnalyzedBullet:
    """Structured analysis of a single resume bullet."""
    bullet_id: str = ""
    text: str = ""
    word_count: int = 0
    tools: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    action_verb: str = ""
    has_quantification: bool = False

    def to_dict(self) -> dict:
        return {
            "bullet_id": self.bullet_id,
            "text": self.text,
            "word_count": self.word_count,
            "tools": self.tools,
            "metrics": self.metrics,
            "action_verb": self.action_verb,
            "has_quantification": self.has_quantification,
        }


# ---------------------------------------------------------------------------
# Metric extraction patterns
# ---------------------------------------------------------------------------

_METRIC_PATTERNS: list[re.Pattern] = [
    # Percentages: 40%, 99.9%
    re.compile(r"\d+(?:\.\d+)?%"),
    # Dollar/money amounts: $1M, $500K, $2.5B
    re.compile(r"\$[\d,]+(?:\.\d+)?[KMBkmb]?"),
    # Large numbers with suffix: 10M+, 500K, 2.5B
    re.compile(r"\d+(?:\.\d+)?[KMBkmb]\+?"),
    # Numbers with commas: 1,000,000
    re.compile(r"\d{1,3}(?:,\d{3})+"),
    # xN multiplier: 3x, 10x
    re.compile(r"\d+x\b"),
    # Time reductions: 40ms, 2 seconds, 50% faster
    re.compile(r"\d+(?:\.\d+)?\s*(?:ms|seconds?|minutes?|hours?|days?)\b"),
    # "N+ requests/day" style
    re.compile(r"\d+\+?\s*(?:requests?|transactions?|users?|records?|queries?|events?)\s*/\s*(?:day|sec|second|minute|hour)", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Action verb detection
# ---------------------------------------------------------------------------

_STRONG_VERBS = {
    "achieved", "architected", "automated", "built", "created", "decreased",
    "delivered", "designed", "developed", "eliminated", "engineered",
    "established", "expanded", "generated", "implemented", "improved",
    "increased", "integrated", "launched", "led", "managed", "mentored",
    "migrated", "optimized", "orchestrated", "pioneered", "rebuilt",
    "reduced", "refactored", "replaced", "scaled", "secured",
    "simplified", "spearheaded", "streamlined", "transformed", "upgraded",
}


def _extract_action_verb(text: str) -> str:
    """Extract the leading action verb from a bullet point."""
    words = text.strip().split()
    if not words:
        return ""
    first_word = words[0].lower().rstrip("ed").rstrip("d")
    # Check the actual first word (may be past tense)
    first_lower = words[0].lower()
    if first_lower in _STRONG_VERBS:
        return first_lower
    # Check common past tense forms
    for verb in _STRONG_VERBS:
        if first_lower.startswith(verb[:4]):
            return first_lower
    return first_lower


def _extract_metrics(text: str) -> list[str]:
    """Extract all quantified metrics from a bullet point."""
    metrics = []
    for pattern in _METRIC_PATTERNS:
        for match in pattern.finditer(text):
            val = match.group()
            if val not in metrics:
                metrics.append(val)
    return metrics


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_bullet(text: str, bullet_id: str = "") -> AnalyzedBullet:
    """Analyze a single resume bullet point.

    Extracts word count, tools, metrics, and action verb.

    >>> b = analyze_bullet("Reduced API latency by 40% serving 10M+ requests/day")
    >>> b.word_count
    8
    >>> "40%" in b.metrics
    True
    >>> b.has_quantification
    True
    """
    cleaned = text.strip()
    # Strip leading bullet characters
    cleaned = re.sub(r"^[-•*·‣]\s*", "", cleaned)

    words = cleaned.split()
    word_count = len(words)

    tools = extract_skills(cleaned)
    metrics = _extract_metrics(cleaned)
    action_verb = _extract_action_verb(cleaned)

    return AnalyzedBullet(
        bullet_id=bullet_id,
        text=cleaned,
        word_count=word_count,
        tools=tools,
        metrics=metrics,
        action_verb=action_verb,
        has_quantification=len(metrics) > 0,
    )


def analyze_bullets(texts: list[str], prefix: str = "bullet") -> list[AnalyzedBullet]:
    """Analyze multiple bullet points.

    >>> bullets = analyze_bullets(["Built ML pipeline", "Reduced costs by 30%"])
    >>> len(bullets)
    2
    >>> bullets[0].bullet_id
    'bullet_0'
    """
    return [
        analyze_bullet(text, bullet_id=f"{prefix}_{i}")
        for i, text in enumerate(texts)
    ]
