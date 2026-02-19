"""Email classification rules engine.

Classifies job-related emails into status categories using keyword matching.
Rules are ordered by priority — highest priority match wins.

SAFETY: This module only reads and classifies. It never modifies anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.models import JobStatus
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class EmailRule:
    """A single classification rule."""
    name: str
    status: JobStatus
    keywords: list[str]
    priority: int  # Higher = takes precedence when multiple rules match
    case_sensitive: bool = False


# Default rules, ordered by priority (highest priority wins on conflict).
# These cover common patterns from job application emails.
DEFAULT_RULES: list[EmailRule] = [
    EmailRule(
        name="offer",
        status=JobStatus.OFFER,
        priority=6,
        keywords=[
            "congratulations",
            "offer letter",
            "pleased to offer",
            "compensation package",
            "start date",
            "offer of employment",
            "we are excited to extend",
            "formal offer",
        ],
    ),
    EmailRule(
        name="interview",
        status=JobStatus.INTERVIEW,
        priority=5,
        keywords=[
            "schedule an interview",
            "interview invitation",
            "phone screen",
            "on-site interview",
            "virtual interview",
            "technical interview",
            "interview with",
            "would like to schedule",
            "availability for",
            "meet the team",
            "hiring manager",
            "next round",
            "we'd like to move forward",
            "move you forward",
            "advance your application",
        ],
    ),
    EmailRule(
        name="assessment",
        status=JobStatus.ASSESSMENT,
        priority=4,
        keywords=[
            "coding challenge",
            "coding test",
            "technical assessment",
            "hackerrank",
            "codility",
            "take-home",
            "online assessment",
            "skills assessment",
            "complete the following",
            "assessment link",
            "codesignal",
            "leetcode",
        ],
    ),
    EmailRule(
        name="reject",
        status=JobStatus.REJECT,
        priority=3,
        keywords=[
            "unfortunately",
            "not moving forward",
            "decided not to proceed",
            "other candidates",
            "we regret",
            "not selected",
            "position has been filled",
            "will not be moving",
            "decided to pursue",
            "after careful consideration",
            "not a match",
            "wish you the best",
            "keep your resume on file",
        ],
    ),
    EmailRule(
        name="applied_ack",
        status=JobStatus.APPLIED,
        priority=2,
        keywords=[
            "thanks for applying",
            "thank you for applying",
            "application received",
            "application submitted",
            "we received your application",
            "successfully submitted",
            "application confirmation",
            "thank you for your interest",
            "we have received your",
            "application has been received",
        ],
    ),
]


@dataclass
class ClassificationResult:
    """Result of classifying an email."""
    status: JobStatus
    rule_name: str
    matched_keyword: str
    confidence: str  # "high" if subject match, "medium" if body match


def classify_email(
    subject: str,
    body: str,
    rules: list[EmailRule] | None = None,
) -> Optional[ClassificationResult]:
    """Classify an email based on subject and body content.

    Checks subject first (higher confidence), then body.
    Returns the highest priority match, or None if no rules match.
    """
    if rules is None:
        rules = DEFAULT_RULES

    best_match: Optional[ClassificationResult] = None
    best_priority = -1

    for rule in rules:
        result = _check_rule(rule, subject, body)
        if result and rule.priority > best_priority:
            best_match = result
            best_priority = rule.priority

    if best_match:
        logger.info(
            f"Classified email as {best_match.status.value} "
            f"(rule={best_match.rule_name}, keyword='{best_match.matched_keyword}', "
            f"confidence={best_match.confidence})"
        )
    else:
        logger.debug(f"No classification match for subject: {subject[:80]}")

    return best_match


def _check_rule(rule: EmailRule, subject: str, body: str) -> Optional[ClassificationResult]:
    """Check if a single rule matches the email."""
    check_subject = subject if rule.case_sensitive else subject.lower()
    check_body = body if rule.case_sensitive else body.lower()

    # Check subject first (higher confidence)
    for keyword in rule.keywords:
        kw = keyword if rule.case_sensitive else keyword.lower()
        if kw in check_subject:
            return ClassificationResult(
                status=rule.status,
                rule_name=rule.name,
                matched_keyword=keyword,
                confidence="high",
            )

    # Then check body
    for keyword in rule.keywords:
        kw = keyword if rule.case_sensitive else keyword.lower()
        if kw in check_body:
            return ClassificationResult(
                status=rule.status,
                rule_name=rule.name,
                matched_keyword=keyword,
                confidence="medium",
            )

    return None
