"""Multi-layer resume rewrite validator.

Validates that every rewrite respects integrity constraints.
Two validation layers:

Layer 1 — Structural Rules:
  - Must start with action verb
  - Must have measurable outcome (preferred, not required)
  - Word count within range

Layer 2 — Integrity Rules:
  - Word count ±3 of original
  - No skills outside skill_inventory_master_list
  - All metrics preserved exactly (numbers, %, $)
  - No platform/tool substitution (AWS ≠ GCP, S3 ≠ GCS)
  - Semantic similarity ≥ threshold with original
  - Named entities preserved (companies, products)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from src.ml.bullet_analyzer import AnalyzedBullet, analyze_bullet, _STRONG_VERBS
from src.ml.rewriter import _is_platform_name, RewriteResult


@dataclass
class ValidationRule:
    """A single validation rule with a name, severity, and check function."""
    name: str
    layer: str          # "structural" or "integrity"
    severity: str       # "error" (blocks approval) or "warning" (informational)
    description: str


@dataclass
class ValidationResult:
    """Result of running all validation rules on a rewrite."""
    passed: bool = True
    errors: list[dict] = field(default_factory=list)    # Blocking issues
    warnings: list[dict] = field(default_factory=list)  # Non-blocking issues
    score: float = 1.0  # 0.0-1.0, deducted per issue

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "errors": self.errors,
            "warnings": self.warnings,
            "score": round(self.score, 3),
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
        }


class RewriteValidator:
    """Validates resume rewrites against structural and integrity rules.

    Usage:
        validator = RewriteValidator(skill_master_list=["Python", "AWS", ...])
        result = validator.validate(original_bullet, rewritten_bullet)

        if not result.passed:
            # Reject the rewrite, keep original
            ...
    """

    def __init__(
        self,
        skill_master_list: list[str] | None = None,
        max_word_delta: int = 3,
        min_similarity: float = 0.60,
    ):
        self.skill_master_list = skill_master_list or []
        self.max_word_delta = max_word_delta
        self.min_similarity = min_similarity
        self._master_lower = {s.lower() for s in self.skill_master_list}

    def validate(
        self,
        original: AnalyzedBullet,
        rewritten: AnalyzedBullet,
    ) -> ValidationResult:
        """Run all validation rules on original vs rewritten bullet."""
        result = ValidationResult()

        # --- Layer 1: Structural Rules ---
        self._check_action_verb(rewritten, result)
        self._check_measurable_outcome(rewritten, result)
        self._check_min_length(rewritten, result)

        # --- Layer 2: Integrity Rules ---
        self._check_word_count_delta(original, rewritten, result)
        self._check_metrics_preserved(original, rewritten, result)
        self._check_no_new_skills(original, rewritten, result)
        self._check_no_platform_swap(original, rewritten, result)
        self._check_semantic_similarity(original, rewritten, result)
        self._check_named_entities(original, rewritten, result)

        # Compute final score and passed status
        result.score = max(0.0, 1.0 - 0.25 * len(result.errors) - 0.05 * len(result.warnings))
        result.passed = len(result.errors) == 0

        return result

    def validate_rewrite_result(self, rr: RewriteResult) -> ValidationResult:
        """Validate a RewriteResult from the rewriter module."""
        return self.validate(rr.original, rr.rewritten_analysis)

    # --- Layer 1: Structural Rules ---

    def _check_action_verb(
        self, bullet: AnalyzedBullet, result: ValidationResult
    ) -> None:
        """Check that bullet starts with a strong action verb."""
        first_word = bullet.text.split()[0].lower() if bullet.text.strip() else ""
        if first_word not in _STRONG_VERBS:
            result.warnings.append({
                "rule": "action_verb",
                "layer": "structural",
                "severity": "warning",
                "message": f"Bullet does not start with a strong action verb (got '{first_word}')",
            })

    def _check_measurable_outcome(
        self, bullet: AnalyzedBullet, result: ValidationResult
    ) -> None:
        """Check that bullet has a measurable outcome (number, %, $)."""
        if not bullet.has_quantification:
            result.warnings.append({
                "rule": "measurable_outcome",
                "layer": "structural",
                "severity": "warning",
                "message": "Bullet lacks quantified metrics (consider adding numbers)",
            })

    def _check_min_length(
        self, bullet: AnalyzedBullet, result: ValidationResult
    ) -> None:
        """Check minimum bullet length."""
        if bullet.word_count < 5:
            result.errors.append({
                "rule": "min_length",
                "layer": "structural",
                "severity": "error",
                "message": f"Bullet too short ({bullet.word_count} words, minimum 5)",
            })

    # --- Layer 2: Integrity Rules ---

    def _check_word_count_delta(
        self,
        original: AnalyzedBullet,
        rewritten: AnalyzedBullet,
        result: ValidationResult,
    ) -> None:
        """Word count must be within ±max_word_delta of original."""
        delta = abs(rewritten.word_count - original.word_count)
        if delta > self.max_word_delta:
            result.errors.append({
                "rule": "word_count_delta",
                "layer": "integrity",
                "severity": "error",
                "message": (
                    f"Word count changed by {delta} "
                    f"(original: {original.word_count}, new: {rewritten.word_count}, "
                    f"max allowed: ±{self.max_word_delta})"
                ),
            })

    def _check_metrics_preserved(
        self,
        original: AnalyzedBullet,
        rewritten: AnalyzedBullet,
        result: ValidationResult,
    ) -> None:
        """All metrics from original must appear exactly in rewritten."""
        for metric in original.metrics:
            if metric not in rewritten.text:
                result.errors.append({
                    "rule": "metrics_preserved",
                    "layer": "integrity",
                    "severity": "error",
                    "message": f"Metric '{metric}' was lost or modified in rewrite",
                })

    def _check_no_new_skills(
        self,
        original: AnalyzedBullet,
        rewritten: AnalyzedBullet,
        result: ValidationResult,
    ) -> None:
        """No skills in rewritten that aren't in the master list or original."""
        if not self._master_lower:
            return  # No master list provided, skip check

        orig_tools_lower = {t.lower() for t in original.tools}

        for tool in rewritten.tools:
            tool_lower = tool.lower()
            if tool_lower not in self._master_lower and tool_lower not in orig_tools_lower:
                result.errors.append({
                    "rule": "no_new_skills",
                    "layer": "integrity",
                    "severity": "error",
                    "message": f"Skill '{tool}' not in resume master list or original bullet",
                })

    def _check_no_platform_swap(
        self,
        original: AnalyzedBullet,
        rewritten: AnalyzedBullet,
        result: ValidationResult,
    ) -> None:
        """No platform/service names added or removed."""
        orig_platforms = {
            t.lower() for t in original.tools if _is_platform_name(t)
        }
        new_platforms = {
            t.lower() for t in rewritten.tools if _is_platform_name(t)
        }

        added = new_platforms - orig_platforms
        removed = orig_platforms - new_platforms

        if added:
            result.errors.append({
                "rule": "no_platform_swap",
                "layer": "integrity",
                "severity": "error",
                "message": f"Platform(s) added: {', '.join(added)}",
            })
        if removed:
            result.errors.append({
                "rule": "no_platform_swap",
                "layer": "integrity",
                "severity": "error",
                "message": f"Platform(s) removed: {', '.join(removed)}",
            })

    def _check_semantic_similarity(
        self,
        original: AnalyzedBullet,
        rewritten: AnalyzedBullet,
        result: ValidationResult,
    ) -> None:
        """Check that rewritten text is semantically similar to original.

        Uses SequenceMatcher as a fast, deterministic proxy for semantic
        similarity. For production, could use embeddings.
        """
        similarity = SequenceMatcher(
            None, original.text.lower(), rewritten.text.lower()
        ).ratio()

        if similarity < self.min_similarity:
            result.errors.append({
                "rule": "semantic_similarity",
                "layer": "integrity",
                "severity": "error",
                "message": (
                    f"Rewrite too different from original "
                    f"(similarity: {similarity:.2f}, minimum: {self.min_similarity})"
                ),
            })

    def _check_named_entities(
        self,
        original: AnalyzedBullet,
        rewritten: AnalyzedBullet,
        result: ValidationResult,
    ) -> None:
        """Check that named entities (capitalized multi-word terms) are preserved."""
        orig_entities = _extract_named_entities(original.text)
        new_entities = _extract_named_entities(rewritten.text)

        # Every entity from original should be in rewritten
        for entity in orig_entities:
            if entity.lower() not in rewritten.text.lower():
                result.warnings.append({
                    "rule": "named_entities",
                    "layer": "integrity",
                    "severity": "warning",
                    "message": f"Named entity '{entity}' may have been modified",
                })


def _extract_named_entities(text: str) -> list[str]:
    """Extract likely named entities (capitalized words not at sentence start)."""
    entities = []
    words = text.split()
    for i, word in enumerate(words):
        # Skip first word (always capitalized in bullets)
        if i == 0:
            continue
        # Look for capitalized words that aren't common abbreviations
        if word[0].isupper() and len(word) > 1 and not word.isupper():
            entities.append(word)
    return entities


# ---------------------------------------------------------------------------
# Batch validation
# ---------------------------------------------------------------------------

def validate_all_rewrites(
    results: list[RewriteResult],
    skill_master_list: list[str],
    max_word_delta: int = 3,
    min_similarity: float = 0.60,
) -> list[ValidationResult]:
    """Validate a batch of rewrite results."""
    validator = RewriteValidator(
        skill_master_list=skill_master_list,
        max_word_delta=max_word_delta,
        min_similarity=min_similarity,
    )
    return [validator.validate_rewrite_result(r) for r in results]
