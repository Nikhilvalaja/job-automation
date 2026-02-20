"""Resume-JD scoring engine.

Computes how well a resume matches a job description using a weighted formula:

    match_score = 0.40 * must_have_coverage
                + 0.20 * title_alignment
                + 0.20 * bullet_similarity_avg
                + 0.10 * domain_alignment
                + 0.10 * tools_overlap

All components are deterministic except bullet_similarity_avg which uses
embeddings (cached). Falls back gracefully when embeddings unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from src.ml.bullet_analyzer import AnalyzedBullet
from src.ml.embeddings import EmbeddingService, cosine_similarity
from src.ml.jd_normalizer import NormalizedJD
from src.ml.resume_parser import ParsedResume
from src.ml.skill_taxonomy import compute_skill_overlap, get_skill_category
from src.ml.title_normalizer import titles_match
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ScoreResult:
    """Detailed scoring result for a JD-resume pair."""
    match_score: float = 0.0

    # Component scores (all 0.0 - 1.0)
    must_have_coverage: float = 0.0
    title_alignment: float = 0.0
    bullet_similarity_avg: float = 0.0
    domain_alignment: float = 0.0
    tools_overlap: float = 0.0

    # Details
    missing_must_haves: list[str] = field(default_factory=list)
    matched_skills: list[str] = field(default_factory=list)
    top_bullets: list[dict] = field(default_factory=list)  # top 6 most relevant
    skill_overlap_detail: dict = field(default_factory=dict)
    recommended_emphasis: str = ""

    def to_dict(self) -> dict:
        return {
            "match_score": round(self.match_score, 4),
            "must_have_coverage": round(self.must_have_coverage, 4),
            "title_alignment": round(self.title_alignment, 4),
            "bullet_similarity_avg": round(self.bullet_similarity_avg, 4),
            "domain_alignment": round(self.domain_alignment, 4),
            "tools_overlap": round(self.tools_overlap, 4),
            "missing_must_haves": self.missing_must_haves,
            "matched_skills": self.matched_skills,
            "top_bullets": self.top_bullets,
            "skill_overlap_detail": self.skill_overlap_detail,
            "recommended_emphasis": self.recommended_emphasis,
        }


# Weight constants
W_MUST_HAVE = 0.40
W_TITLE = 0.20
W_BULLET_SIM = 0.20
W_DOMAIN = 0.10
W_TOOLS = 0.10


class ResumeScorer:
    """Scores how well a resume matches a job description."""

    def __init__(self, embedding_service: EmbeddingService | None = None) -> None:
        self._embeddings = embedding_service or EmbeddingService()

    def score(self, jd: NormalizedJD, resume: ParsedResume) -> ScoreResult:
        """Compute match score between a JD and a resume.

        Args:
            jd: Normalized job description
            resume: Parsed resume

        Returns:
            ScoreResult with overall score and component breakdown
        """
        result = ScoreResult()

        # 1. Must-have skill coverage (0.40 weight)
        result.must_have_coverage, result.missing_must_haves, result.matched_skills = (
            self._compute_must_have_coverage(jd, resume)
        )

        # 2. Title alignment (0.20 weight)
        result.title_alignment = self._compute_title_alignment(jd, resume)

        # 3. Bullet similarity (0.20 weight)
        result.bullet_similarity_avg, result.top_bullets = (
            self._compute_bullet_similarity(jd, resume)
        )

        # 4. Domain alignment (0.10 weight)
        result.domain_alignment = self._compute_domain_alignment(jd, resume)

        # 5. Tools overlap (0.10 weight)
        overlap = compute_skill_overlap(jd.all_skills, resume.skill_inventory_master_list)
        result.tools_overlap = overlap["overlap_pct"]
        result.skill_overlap_detail = overlap

        # Weighted sum
        result.match_score = (
            W_MUST_HAVE * result.must_have_coverage
            + W_TITLE * result.title_alignment
            + W_BULLET_SIM * result.bullet_similarity_avg
            + W_DOMAIN * result.domain_alignment
            + W_TOOLS * result.tools_overlap
        )

        # Determine emphasis recommendation
        result.recommended_emphasis = self._recommend_emphasis(jd, result)

        logger.debug(
            f"Score: {result.match_score:.3f} "
            f"(must={result.must_have_coverage:.2f}, title={result.title_alignment:.2f}, "
            f"bullet={result.bullet_similarity_avg:.2f}, domain={result.domain_alignment:.2f}, "
            f"tools={result.tools_overlap:.2f})"
        )

        return result

    def _compute_must_have_coverage(
        self, jd: NormalizedJD, resume: ParsedResume
    ) -> tuple[float, list[str], list[str]]:
        """Compute what fraction of must-have skills the resume covers.

        Returns (coverage_pct, missing_skills, matched_skills).
        """
        must_haves = jd.must_have_skills
        if not must_haves:
            # If no must-haves detected, use all skills
            must_haves = jd.all_skills
        if not must_haves:
            return 1.0, [], []  # No requirements = perfect match

        resume_skills = set(resume.skill_inventory_master_list)
        matched = [s for s in must_haves if s in resume_skills]
        missing = [s for s in must_haves if s not in resume_skills]

        coverage = len(matched) / len(must_haves) if must_haves else 1.0
        return coverage, missing, matched

    def _compute_title_alignment(
        self, jd: NormalizedJD, resume: ParsedResume
    ) -> float:
        """Compute how well the JD title matches the resume's experience titles."""
        if not resume.experience:
            return 0.5  # neutral if no experience parsed

        best_match = 0.0
        for entry in resume.experience:
            if entry.role:
                score = titles_match(jd.title_raw, entry.role)
                best_match = max(best_match, score)

        return best_match

    def _compute_bullet_similarity(
        self, jd: NormalizedJD, resume: ParsedResume
    ) -> tuple[float, list[dict]]:
        """Compute average similarity of top resume bullets to JD.

        Returns (avg_similarity, top_6_bullets).
        """
        all_bullets: list[AnalyzedBullet] = []
        for entry in resume.experience:
            all_bullets.extend(entry.bullets)

        if not all_bullets or not jd.cleaned_text:
            return 0.5, []  # neutral default

        # Get JD embedding
        jd_embedding = self._embeddings.embed_text(jd.cleaned_text[:3000])

        # Get bullet embeddings
        bullet_texts = [b.text for b in all_bullets]
        bullet_embeddings = self._embeddings.embed_batch(bullet_texts)

        # Compute similarities
        scored_bullets: list[tuple[float, AnalyzedBullet]] = []
        for bullet, embedding in zip(all_bullets, bullet_embeddings):
            sim = cosine_similarity(jd_embedding, embedding)
            scored_bullets.append((sim, bullet))

        # Sort by similarity (highest first)
        scored_bullets.sort(key=lambda x: x[0], reverse=True)

        # Top 6 bullets
        top_6 = scored_bullets[:6]
        top_bullets = [
            {
                "bullet_id": b.bullet_id,
                "text": b.text,
                "similarity": round(sim, 4),
                "tools": b.tools,
                "metrics": b.metrics,
            }
            for sim, b in top_6
        ]

        # Average similarity of top 6
        if top_6:
            avg_sim = sum(sim for sim, _ in top_6) / len(top_6)
        else:
            avg_sim = 0.0

        return avg_sim, top_bullets

    def _compute_domain_alignment(
        self, jd: NormalizedJD, resume: ParsedResume
    ) -> float:
        """Compute domain alignment by comparing skill category distributions."""
        if not jd.skill_categories or not resume.skill_categories:
            return 0.5  # neutral

        jd_cats = set(jd.skill_categories.keys())
        resume_cats = set(resume.skill_categories.keys())

        if not jd_cats:
            return 0.5

        overlap = jd_cats & resume_cats
        return len(overlap) / len(jd_cats)

    def _recommend_emphasis(self, jd: NormalizedJD, result: ScoreResult) -> str:
        """Generate a recommendation for resume emphasis."""
        if result.match_score >= 0.85:
            return "strong_match"
        elif result.match_score >= 0.65:
            if result.must_have_coverage < 0.7:
                return "skill_gap"
            elif result.bullet_similarity_avg < 0.5:
                return "reword_bullets"
            else:
                return "good_match"
        elif result.match_score >= 0.4:
            return "moderate_match"
        else:
            return "weak_match"
