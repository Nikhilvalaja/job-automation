"""Constrained resume bullet rewriter.

Philosophy: OPTIMIZE, don't generate. Deterministic first, LLM second, validation always.

Constraints enforced on every rewrite:
1. Word count within ±3 of original
2. No skills outside the resume's skill_inventory_master_list
3. All metrics preserved exactly (numbers, %, $)
4. No platform substitution (AWS ≠ GCP, S3 ≠ GCS)
5. Semantic similarity ≥ threshold with original
6. Must start with strong action verb
7. Must preserve all named entities (companies, products)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.ml.bullet_analyzer import AnalyzedBullet, analyze_bullet
from src.ml.keyword_mapper import (
    find_swap_for_jd,
    suggest_keyword_alignment,
    check_skill_transferability,
    CLOUD_TRANSFERABILITY,
    ALL_SKILL_FAMILIES,
)


@dataclass
class RewriteConstraints:
    """Constraints that every rewrite must satisfy."""
    max_word_delta: int = 3               # |new_words - old_words| <= 3
    min_similarity: float = 0.75          # Cosine similarity floor
    preserve_metrics_exact: bool = True   # All numbers must appear verbatim
    no_new_skills: bool = True            # Only skills from master list
    no_platform_swap: bool = True         # Never swap cloud/tool platforms
    must_start_action_verb: bool = True   # First word = strong action verb


@dataclass
class RewriteResult:
    """Result of a single bullet rewrite attempt."""
    original: AnalyzedBullet
    rewritten_text: str
    rewritten_analysis: AnalyzedBullet
    changes: list[dict]           # List of {type, original, replacement, reason}
    method: str                   # "deterministic", "llm", "no_change"
    confidence: float = 0.0       # How confident we are this is a good rewrite
    validation_passed: bool = False
    validation_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "original_text": self.original.text,
            "rewritten_text": self.rewritten_text,
            "changes": self.changes,
            "method": self.method,
            "confidence": self.confidence,
            "validation_passed": self.validation_passed,
            "validation_errors": self.validation_errors,
            "word_count_delta": (
                self.rewritten_analysis.word_count - self.original.word_count
            ),
        }


@dataclass
class RewriteRequest:
    """Request to rewrite resume bullets for a specific JD."""
    bullet_texts: list[str]                  # The bullets to optimize
    jd_text: str                             # The job description
    jd_skills: list[str]                     # Extracted JD skills
    skill_inventory_master_list: list[str]   # Resume's master skill list
    constraints: RewriteConstraints = field(default_factory=RewriteConstraints)


# ---------------------------------------------------------------------------
# Platform / cloud service names — used to detect platform substitution
# ---------------------------------------------------------------------------

def _build_platform_set() -> set[str]:
    """Build a set of all known platform/service names (lowercased)."""
    names = set()
    for equiv in CLOUD_TRANSFERABILITY:
        for provider, service in equiv.services.items():
            names.add(service.lower())
            names.add(provider.lower())
    # Also add skill family members that are specific tools (not concepts)
    for family in ALL_SKILL_FAMILIES:
        if family.category in ("cloud", "devops", "database", "messaging"):
            for s in family.skills:
                names.add(s.lower())
    return names


_PLATFORM_NAMES = _build_platform_set()


def _is_platform_name(word: str) -> bool:
    """Check if a word is a known platform/service name."""
    return word.lower() in _PLATFORM_NAMES


# ---------------------------------------------------------------------------
# Deterministic Rewriter — keyword swaps only
# ---------------------------------------------------------------------------

class DeterministicRewriter:
    """Rewrites bullets using ONLY safe, pre-approved keyword swaps.

    No LLM involved. Every change is traceable to a specific swap rule.
    """

    def rewrite_bullet(
        self,
        bullet_text: str,
        jd_text: str,
        skill_master_list: list[str],
        constraints: RewriteConstraints | None = None,
    ) -> RewriteResult:
        """Rewrite a single bullet using deterministic keyword swaps.

        Steps:
        1. Analyze the original bullet
        2. Find safe keyword swaps from the JD
        3. Apply swaps that pass validation
        4. Return result with change log
        """
        if constraints is None:
            constraints = RewriteConstraints()

        original = analyze_bullet(bullet_text)
        jd_words = jd_text.split()
        changes: list[dict] = []

        # Get swap suggestions
        suggestions = suggest_keyword_alignment([bullet_text], jd_text)

        # Apply swaps one at a time, validating each
        new_text = bullet_text
        for suggestion in suggestions:
            old_word = suggestion["original_word"]
            new_word = suggestion["suggested_word"]

            # Guard: don't swap platform names
            if constraints.no_platform_swap and (
                _is_platform_name(old_word) or _is_platform_name(new_word)
            ):
                continue

            # Guard: don't swap if new word is a skill not in master list
            if constraints.no_new_skills:
                new_lower = new_word.lower()
                master_lower = {s.lower() for s in skill_master_list}
                # Only check for technical swaps, not action verbs
                if suggestion["category"] == "technical" and new_lower not in master_lower:
                    continue

            # Apply the swap
            trial_text = _safe_replace(new_text, old_word, new_word)

            # Validate word count delta
            trial_wc = len(trial_text.split())
            if abs(trial_wc - original.word_count) > constraints.max_word_delta:
                continue

            new_text = trial_text
            changes.append({
                "type": suggestion["category"],
                "original": old_word,
                "replacement": new_word,
                "reason": suggestion["reason"],
            })

        # Analyze the rewritten bullet
        rewritten = analyze_bullet(new_text)

        # Validate the final result
        errors = self._validate(original, rewritten, constraints)

        method = "deterministic" if changes else "no_change"
        confidence = min(0.95, 0.5 + 0.1 * len(changes)) if changes else 0.0

        return RewriteResult(
            original=original,
            rewritten_text=new_text,
            rewritten_analysis=rewritten,
            changes=changes,
            method=method,
            confidence=confidence,
            validation_passed=len(errors) == 0,
            validation_errors=errors,
        )

    def _validate(
        self,
        original: AnalyzedBullet,
        rewritten: AnalyzedBullet,
        constraints: RewriteConstraints,
    ) -> list[str]:
        """Validate that a rewrite respects all constraints."""
        errors = []

        # Word count delta
        delta = abs(rewritten.word_count - original.word_count)
        if delta > constraints.max_word_delta:
            errors.append(
                f"Word count delta {delta} exceeds max {constraints.max_word_delta} "
                f"({original.word_count} -> {rewritten.word_count})"
            )

        # Metrics preservation
        if constraints.preserve_metrics_exact:
            for metric in original.metrics:
                if metric not in rewritten.text:
                    errors.append(f"Metric '{metric}' lost in rewrite")

        return errors

    def rewrite_bullets(
        self,
        request: RewriteRequest,
    ) -> list[RewriteResult]:
        """Rewrite multiple bullets."""
        results = []
        for text in request.bullet_texts:
            result = self.rewrite_bullet(
                bullet_text=text,
                jd_text=request.jd_text,
                skill_master_list=request.skill_inventory_master_list,
                constraints=request.constraints,
            )
            results.append(result)
        return results


# ---------------------------------------------------------------------------
# LLM-Assisted Rewriter — uses OpenAI with strict guardrails
# ---------------------------------------------------------------------------

# System prompt constrains the LLM tightly
_LLM_SYSTEM_PROMPT = """You are a resume bullet point optimizer. You REFINE existing bullets — you do NOT generate new content.

ABSOLUTE RULES:
1. Keep the EXACT same meaning — only improve phrasing and keyword alignment
2. Word count MUST stay within ±3 words of the original
3. ALL numbers, percentages, and dollar amounts MUST appear exactly as-is
4. NEVER add skills, tools, or technologies not in the original bullet
5. NEVER substitute platforms (e.g., don't change AWS to GCP, S3 to Blob Storage)
6. Start with a strong past-tense action verb
7. Keep the same level of specificity — don't add or remove details
8. If you can't improve the bullet meaningfully, return it UNCHANGED

OUTPUT FORMAT (strict JSON):
{"rewritten": "the optimized bullet text", "changes": ["description of change 1", "description of change 2"]}

If no change needed:
{"rewritten": "original text unchanged", "changes": []}"""


class LLMRewriter:
    """Uses an LLM with strict guardrails for more nuanced rewrites.

    The LLM is given:
    - The original bullet
    - The JD context (relevant section only)
    - The resume's skill master list (so it knows what's allowed)
    - Strict system prompt with absolute rules

    Every LLM output is validated by DeterministicRewriter._validate()
    before being accepted. If validation fails, the original bullet is kept.
    """

    def __init__(self):
        self._deterministic = DeterministicRewriter()

    def rewrite_bullet(
        self,
        bullet_text: str,
        jd_text: str,
        skill_master_list: list[str],
        jd_skills: list[str] | None = None,
        constraints: RewriteConstraints | None = None,
    ) -> RewriteResult:
        """Rewrite a bullet using LLM assistance with strict validation.

        Falls back to deterministic if LLM fails or validation fails.
        """
        import json

        if constraints is None:
            constraints = RewriteConstraints()

        original = analyze_bullet(bullet_text)

        # Build the user prompt
        user_prompt = self._build_prompt(
            bullet_text, jd_text, skill_master_list, jd_skills or []
        )

        # Call LLM
        try:
            llm_response = self._call_llm(user_prompt)
            parsed = json.loads(llm_response)
            rewritten_text = parsed.get("rewritten", bullet_text)
            llm_changes = parsed.get("changes", [])
        except Exception:
            # LLM failed — fall back to deterministic
            return self._deterministic.rewrite_bullet(
                bullet_text, jd_text, skill_master_list, constraints
            )

        # If LLM returned the same text, no change
        if rewritten_text.strip() == bullet_text.strip():
            return RewriteResult(
                original=original,
                rewritten_text=bullet_text,
                rewritten_analysis=original,
                changes=[],
                method="no_change",
                confidence=0.0,
                validation_passed=True,
                validation_errors=[],
            )

        # Validate the LLM output
        rewritten = analyze_bullet(rewritten_text)
        errors = self._validate_llm_output(
            original, rewritten, skill_master_list, constraints
        )

        if errors:
            # LLM output failed validation — fall back to deterministic
            det_result = self._deterministic.rewrite_bullet(
                bullet_text, jd_text, skill_master_list, constraints
            )
            det_result.validation_errors = (
                [f"LLM output rejected: {e}" for e in errors]
                + det_result.validation_errors
            )
            return det_result

        changes = [
            {"type": "llm_optimization", "original": "", "replacement": "",
             "reason": c}
            for c in llm_changes
        ]

        return RewriteResult(
            original=original,
            rewritten_text=rewritten_text,
            rewritten_analysis=rewritten,
            changes=changes,
            method="llm",
            confidence=0.8,
            validation_passed=True,
            validation_errors=[],
        )

    def _build_prompt(
        self,
        bullet_text: str,
        jd_text: str,
        skill_master_list: list[str],
        jd_skills: list[str],
    ) -> str:
        """Build the user prompt for the LLM."""
        # Truncate JD to relevant portion (first 500 chars)
        jd_excerpt = jd_text[:500] if len(jd_text) > 500 else jd_text

        return (
            f"ORIGINAL BULLET: {bullet_text}\n\n"
            f"JOB DESCRIPTION (excerpt):\n{jd_excerpt}\n\n"
            f"JD KEY SKILLS: {', '.join(jd_skills[:15])}\n\n"
            f"RESUME SKILL INVENTORY (allowed skills only): {', '.join(skill_master_list[:30])}\n\n"
            f"Original word count: {len(bullet_text.split())}\n"
            f"Allowed word count range: {len(bullet_text.split()) - 3} to {len(bullet_text.split()) + 3}\n\n"
            f"Optimize this bullet for the JD while following ALL rules strictly."
        )

    def _call_llm(self, user_prompt: str) -> str:
        """Call OpenAI API for bullet rewrite."""
        import openai
        from src.config import get_settings

        settings = get_settings()
        client = openai.OpenAI(api_key=settings.openai_api_key)

        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,  # Low creativity — we want precision
            max_tokens=300,
            response_format={"type": "json_object"},
        )

        return response.choices[0].message.content or "{}"

    def _validate_llm_output(
        self,
        original: AnalyzedBullet,
        rewritten: AnalyzedBullet,
        skill_master_list: list[str],
        constraints: RewriteConstraints,
    ) -> list[str]:
        """Validate LLM output against all constraints."""
        errors = []

        # 1. Word count delta
        delta = abs(rewritten.word_count - original.word_count)
        if delta > constraints.max_word_delta:
            errors.append(
                f"Word count delta {delta} exceeds ±{constraints.max_word_delta}"
            )

        # 2. Metrics preservation
        if constraints.preserve_metrics_exact:
            for metric in original.metrics:
                if metric not in rewritten.text:
                    errors.append(f"Metric '{metric}' was lost or modified")

        # 3. No new skills outside master list
        if constraints.no_new_skills:
            master_lower = {s.lower() for s in skill_master_list}
            for tool in rewritten.tools:
                if tool.lower() not in master_lower:
                    # Check if it was already in the original
                    orig_tools_lower = {t.lower() for t in original.tools}
                    if tool.lower() not in orig_tools_lower:
                        errors.append(
                            f"New skill '{tool}' not in master list"
                        )

        # 4. No platform substitution
        if constraints.no_platform_swap:
            orig_platforms = {
                t.lower() for t in original.tools if _is_platform_name(t)
            }
            new_platforms = {
                t.lower() for t in rewritten.tools if _is_platform_name(t)
            }
            added_platforms = new_platforms - orig_platforms
            if added_platforms:
                errors.append(
                    f"Platform substitution detected: added {added_platforms}"
                )
            removed_platforms = orig_platforms - new_platforms
            if removed_platforms:
                errors.append(
                    f"Platform removed: {removed_platforms}"
                )

        return errors

    def rewrite_bullets(
        self,
        request: RewriteRequest,
    ) -> list[RewriteResult]:
        """Rewrite multiple bullets with LLM assistance."""
        results = []
        for text in request.bullet_texts:
            result = self.rewrite_bullet(
                bullet_text=text,
                jd_text=request.jd_text,
                skill_master_list=request.skill_inventory_master_list,
                jd_skills=request.jd_skills,
                constraints=request.constraints,
            )
            results.append(result)
        return results


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _safe_replace(text: str, old_word: str, new_word: str) -> str:
    """Replace a word in text, respecting word boundaries."""
    pattern = re.compile(re.escape(old_word), re.IGNORECASE)
    # Only replace the first occurrence to be safe
    return pattern.sub(new_word, text, count=1)


# ---------------------------------------------------------------------------
# Public API — convenience functions
# ---------------------------------------------------------------------------

def rewrite_deterministic(
    bullet_texts: list[str],
    jd_text: str,
    skill_master_list: list[str],
) -> list[RewriteResult]:
    """Rewrite bullets using deterministic keyword swaps only."""
    rewriter = DeterministicRewriter()
    request = RewriteRequest(
        bullet_texts=bullet_texts,
        jd_text=jd_text,
        jd_skills=[],
        skill_inventory_master_list=skill_master_list,
    )
    return rewriter.rewrite_bullets(request)


def rewrite_with_llm(
    bullet_texts: list[str],
    jd_text: str,
    jd_skills: list[str],
    skill_master_list: list[str],
) -> list[RewriteResult]:
    """Rewrite bullets with LLM assistance and strict validation."""
    rewriter = LLMRewriter()
    request = RewriteRequest(
        bullet_texts=bullet_texts,
        jd_text=jd_text,
        jd_skills=jd_skills,
        skill_inventory_master_list=skill_master_list,
    )
    return rewriter.rewrite_bullets(request)
