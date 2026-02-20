"""Diff report generator — side-by-side comparison with highlights.

Generates structured diff reports showing:
- Original vs rewritten bullets side-by-side
- Word-level change highlights
- Validation status per bullet
- Overall summary statistics
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from src.ml.rewriter import RewriteResult
from src.ml.validator import ValidationResult


@dataclass
class BulletDiff:
    """Diff for a single bullet."""
    index: int
    original_text: str
    rewritten_text: str
    changed: bool
    changes: list[dict]             # From RewriteResult
    word_diffs: list[dict]          # Word-level: {type, value}
    validation: ValidationResult | None = None
    approved: bool | None = None    # None = pending, True = approved, False = rejected

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "original_text": self.original_text,
            "rewritten_text": self.rewritten_text,
            "changed": self.changed,
            "changes": self.changes,
            "word_diffs": self.word_diffs,
            "validation": self.validation.to_dict() if self.validation else None,
            "approved": self.approved,
        }


@dataclass
class DiffReport:
    """Full diff report for a resume rewrite session."""
    bullet_diffs: list[BulletDiff] = field(default_factory=list)
    total_bullets: int = 0
    changed_bullets: int = 0
    approved_bullets: int = 0
    rejected_bullets: int = 0
    pending_bullets: int = 0
    validation_pass_rate: float = 0.0

    def to_dict(self) -> dict:
        return {
            "bullet_diffs": [d.to_dict() for d in self.bullet_diffs],
            "summary": {
                "total_bullets": self.total_bullets,
                "changed_bullets": self.changed_bullets,
                "approved_bullets": self.approved_bullets,
                "rejected_bullets": self.rejected_bullets,
                "pending_bullets": self.pending_bullets,
                "validation_pass_rate": round(self.validation_pass_rate, 3),
            },
        }


def compute_word_diffs(original: str, rewritten: str) -> list[dict]:
    """Compute word-level diffs between original and rewritten text.

    Returns a list of diff operations:
    - {"type": "equal", "value": "word"}
    - {"type": "delete", "value": "old_word"}
    - {"type": "insert", "value": "new_word"}
    - {"type": "replace", "old": "old_word", "new": "new_word"}
    """
    orig_words = original.split()
    new_words = rewritten.split()

    matcher = SequenceMatcher(None, orig_words, new_words)
    diffs = []

    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            for w in orig_words[i1:i2]:
                diffs.append({"type": "equal", "value": w})
        elif op == "delete":
            for w in orig_words[i1:i2]:
                diffs.append({"type": "delete", "value": w})
        elif op == "insert":
            for w in new_words[j1:j2]:
                diffs.append({"type": "insert", "value": w})
        elif op == "replace":
            old_chunk = orig_words[i1:i2]
            new_chunk = new_words[j1:j2]
            # Pair up replacements where possible
            max_len = max(len(old_chunk), len(new_chunk))
            for k in range(max_len):
                old_w = old_chunk[k] if k < len(old_chunk) else None
                new_w = new_chunk[k] if k < len(new_chunk) else None
                if old_w and new_w:
                    diffs.append({
                        "type": "replace", "old": old_w, "new": new_w,
                    })
                elif old_w:
                    diffs.append({"type": "delete", "value": old_w})
                elif new_w:
                    diffs.append({"type": "insert", "value": new_w})

    return diffs


def generate_diff_report(
    rewrite_results: list[RewriteResult],
    validation_results: list[ValidationResult] | None = None,
) -> DiffReport:
    """Generate a full diff report from rewrite and validation results.

    Args:
        rewrite_results: Output from DeterministicRewriter or LLMRewriter
        validation_results: Optional validation results (one per rewrite)

    Returns:
        DiffReport with per-bullet diffs and summary stats
    """
    bullet_diffs = []

    for i, rr in enumerate(rewrite_results):
        changed = rr.method != "no_change"
        word_diffs = (
            compute_word_diffs(rr.original.text, rr.rewritten_text)
            if changed else []
        )

        vr = validation_results[i] if validation_results and i < len(validation_results) else None

        bullet_diffs.append(BulletDiff(
            index=i,
            original_text=rr.original.text,
            rewritten_text=rr.rewritten_text,
            changed=changed,
            changes=rr.changes,
            word_diffs=word_diffs,
            validation=vr,
            approved=None,  # Pending user review
        ))

    # Summary stats
    total = len(bullet_diffs)
    changed = sum(1 for d in bullet_diffs if d.changed)
    approved = sum(1 for d in bullet_diffs if d.approved is True)
    rejected = sum(1 for d in bullet_diffs if d.approved is False)
    pending = sum(1 for d in bullet_diffs if d.approved is None)

    pass_count = 0
    if validation_results:
        pass_count = sum(1 for v in validation_results if v.passed)

    return DiffReport(
        bullet_diffs=bullet_diffs,
        total_bullets=total,
        changed_bullets=changed,
        approved_bullets=approved,
        rejected_bullets=rejected,
        pending_bullets=pending,
        validation_pass_rate=pass_count / max(total, 1),
    )


def render_diff_text(report: DiffReport) -> str:
    """Render a diff report as plain text for terminal/log output."""
    lines = []
    lines.append(f"=== Resume Diff Report ===")
    lines.append(
        f"Total: {report.total_bullets} | "
        f"Changed: {report.changed_bullets} | "
        f"Validation pass rate: {report.validation_pass_rate:.0%}"
    )
    lines.append("")

    for d in report.bullet_diffs:
        status = "CHANGED" if d.changed else "UNCHANGED"
        valid = ""
        if d.validation:
            valid = " [VALID]" if d.validation.passed else " [INVALID]"

        lines.append(f"--- Bullet {d.index + 1} ({status}{valid}) ---")
        lines.append(f"  Original:  {d.original_text}")
        if d.changed:
            lines.append(f"  Rewritten: {d.rewritten_text}")
            for c in d.changes:
                lines.append(f"    * {c.get('original', '')} -> {c.get('replacement', '')} ({c.get('reason', '')})")
        lines.append("")

    return "\n".join(lines)


def render_diff_html(report: DiffReport) -> str:
    """Render a diff report as HTML for dashboard display.

    Uses <span> tags with classes for styling:
    - .diff-equal: unchanged words
    - .diff-delete: removed words (red, strikethrough)
    - .diff-insert: added words (green, bold)
    - .diff-replace-old: replaced words (red, strikethrough)
    - .diff-replace-new: replacement words (green, bold)
    """
    parts = []

    for d in report.bullet_diffs:
        if not d.changed:
            parts.append(
                f'<div class="bullet-diff unchanged">'
                f'<span class="bullet-status">&#x2713;</span> '
                f'<span class="diff-equal">{_html_escape(d.original_text)}</span>'
                f'</div>'
            )
            continue

        # Render word diffs
        diff_html = []
        for wd in d.word_diffs:
            if wd["type"] == "equal":
                diff_html.append(f'<span class="diff-equal">{_html_escape(wd["value"])}</span>')
            elif wd["type"] == "delete":
                diff_html.append(f'<span class="diff-delete">{_html_escape(wd["value"])}</span>')
            elif wd["type"] == "insert":
                diff_html.append(f'<span class="diff-insert">{_html_escape(wd["value"])}</span>')
            elif wd["type"] == "replace":
                diff_html.append(
                    f'<span class="diff-replace-old">{_html_escape(wd["old"])}</span>'
                    f'<span class="diff-replace-new">{_html_escape(wd["new"])}</span>'
                )

        valid_class = ""
        if d.validation:
            valid_class = " valid" if d.validation.passed else " invalid"

        parts.append(
            f'<div class="bullet-diff changed{valid_class}">'
            f'<span class="bullet-status">&#x270E;</span> '
            + " ".join(diff_html)
            + '</div>'
        )

    return "\n".join(parts)


def _html_escape(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
