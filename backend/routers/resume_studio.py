"""Resume Studio API router — rewrite, validate, approve, export endpoints.

Endpoints:
  POST /studio/rewrite          — Rewrite resume bullets for a JD
  POST /studio/rewrite-llm      — Rewrite with LLM assistance
  GET  /studio/variants         — List all variants
  GET  /studio/variants/{id}    — Get variant with bullet details
  DELETE /studio/variants/{id}  — Delete a variant
  PATCH /studio/variants/{id}/bullet/{idx}  — Approve/reject/edit a bullet
  POST /studio/variants/{id}/finalize       — Finalize variant
  POST /studio/variants/{id}/transition     — Transition status
  POST /studio/variants/{id}/interview      — Mark interview callback
  GET  /studio/stats            — Variant stats + bullet analytics
  POST /studio/skill-transfer   — Check skill transferability
  POST /studio/gap-analysis     — Full skill gap analysis (v2)
"""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/studio", tags=["resume-studio"])


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

class RewriteRequest(BaseModel):
    resume_id: str
    jd_title: str = ""
    jd_company: str = ""
    jd_text: str
    bullet_texts: list[str] = Field(default_factory=list)
    jd_skills: list[str] = Field(default_factory=list)


class RewriteLLMRequest(RewriteRequest):
    """Same as RewriteRequest but explicitly uses LLM."""
    pass


class BulletApprovalRequest(BaseModel):
    approval: str  # "approved", "rejected", "pending"
    user_edited_text: str | None = None


class StatusTransitionRequest(BaseModel):
    new_status: str


class SkillTransferRequest(BaseModel):
    source_skill: str
    target_skill: str


class GapAnalysisRequest(BaseModel):
    resume_skills: list[str]
    jd_skills: list[str]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/rewrite")
def rewrite_bullets(req: RewriteRequest):
    """Rewrite resume bullets using deterministic keyword swaps.

    Steps:
    1. Load resume from store (get skill master list)
    2. Run deterministic rewriter
    3. Validate all rewrites
    4. Generate diff report
    5. Run skill gap analysis (v2)
    6. Save as new variant (never overwrite original)
    7. Return variant with diff report
    """
    from src.ml.resume_store import get_resume
    from src.ml.resume_parser import ResumeParser
    from src.ml.rewriter import DeterministicRewriter, RewriteRequest as RR, RewriteConstraints
    from src.ml.validator import validate_all_rewrites
    from src.ml.diff_report import generate_diff_report
    from src.ml.skill_registry import analyze_skill_gaps_v2
    from src.ml.variant_store import save_variant
    from src.ml.skill_taxonomy import extract_skills

    # Load resume
    resume = get_resume(req.resume_id)
    if not resume:
        raise HTTPException(404, f"Resume '{req.resume_id}' not found")

    # Get skill master list
    skill_master = resume.get("skill_inventory") or []
    if not skill_master and resume.get("raw_text"):
        parser = ResumeParser()
        parsed = parser.parse(resume["raw_text"])
        skill_master = parsed.skill_inventory_master_list

    # Get bullets from request or parse from resume
    bullet_texts = req.bullet_texts
    if not bullet_texts and resume.get("raw_text"):
        parser = ResumeParser()
        parsed = parser.parse(resume["raw_text"])
        bullet_texts = [
            b.text for e in parsed.experience for b in e.bullets
        ]

    if not bullet_texts:
        raise HTTPException(400, "No bullets to rewrite")

    # Extract JD skills if not provided
    jd_skills = req.jd_skills
    if not jd_skills:
        jd_skills = extract_skills(req.jd_text)

    # Run deterministic rewriter
    rewriter = DeterministicRewriter()
    rr = RR(
        bullet_texts=bullet_texts,
        jd_text=req.jd_text,
        jd_skills=jd_skills,
        skill_inventory_master_list=skill_master,
    )
    rewrite_results = rewriter.rewrite_bullets(rr)

    # Validate all rewrites
    validation_results = validate_all_rewrites(rewrite_results, skill_master)

    # Generate diff report
    diff_report = generate_diff_report(rewrite_results, validation_results)

    # Run skill gap analysis (v2 — computed per-skill transfer)
    gap_analysis = analyze_skill_gaps_v2(skill_master, jd_skills)

    # Compute resume hash for version tracking
    resume_hash = hashlib.md5(
        (resume.get("raw_text", "") or "").encode()
    ).hexdigest()[:12]

    # Build bullet data for variant store
    bullets_data = []
    for rr_item, vr in zip(rewrite_results, validation_results):
        bullets_data.append({
            "original_text": rr_item.original.text,
            "rewritten_text": rr_item.rewritten_text,
            "changes": rr_item.changes,
            "validation": {
                "word_count_ok": not any(
                    e["rule"] == "word_count_delta" for e in vr.errors
                ),
                "no_new_skills_ok": not any(
                    e["rule"] == "no_new_skills" for e in vr.errors
                ),
                "metrics_preserved_ok": not any(
                    e["rule"] == "metrics_preserved" for e in vr.errors
                ),
                "semantic_similarity_score": _get_similarity(vr),
                "action_verb_ok": not any(
                    e["rule"] == "action_verb" for e in vr.warnings
                ),
                "platform_swap_ok": not any(
                    e["rule"] == "no_platform_swap" for e in vr.errors
                ),
                "validation_passed": vr.passed,
                "errors": [e["message"] for e in vr.errors],
            },
        })

    # Save variant
    variant = save_variant(
        parent_resume_id=req.resume_id,
        jd_title=req.jd_title,
        jd_company=req.jd_company,
        jd_text=req.jd_text,
        method="deterministic",
        bullets=bullets_data,
        diff_report=diff_report.to_dict(),
        gap_analysis=gap_analysis,
        jd_skills=jd_skills,
        jd_cleaned_text=req.jd_text[:2000],
        resume_hash=resume_hash,
        match_score=gap_analysis.get("match_rate", 0.0),
        weighted_score=gap_analysis.get("weighted_score", 0.0),
        coverage_rate=gap_analysis.get("coverage_rate", 0.0),
        exact_match_count=len(gap_analysis.get("exact_matches", [])),
        transferable_count=len(gap_analysis.get("transferable", [])),
        gap_count=len(gap_analysis.get("gaps", [])),
        validation_pass_rate=diff_report.validation_pass_rate,
    )

    return {
        "variant": variant,
        "diff_report": diff_report.to_dict(),
        "gap_analysis": gap_analysis,
        "rewrite_count": diff_report.changed_bullets,
        "total_bullets": diff_report.total_bullets,
    }


@router.post("/rewrite-llm")
def rewrite_bullets_llm(req: RewriteLLMRequest):
    """Rewrite with LLM assistance — same flow but uses LLMRewriter.

    Falls back to deterministic if LLM fails validation.
    """
    from src.ml.resume_store import get_resume
    from src.ml.resume_parser import ResumeParser
    from src.ml.rewriter import LLMRewriter, RewriteRequest as RR
    from src.ml.validator import validate_all_rewrites
    from src.ml.diff_report import generate_diff_report
    from src.ml.skill_registry import analyze_skill_gaps_v2
    from src.ml.variant_store import save_variant
    from src.ml.skill_taxonomy import extract_skills

    resume = get_resume(req.resume_id)
    if not resume:
        raise HTTPException(404, f"Resume '{req.resume_id}' not found")

    skill_master = resume.get("skill_inventory") or []
    if not skill_master and resume.get("raw_text"):
        parser = ResumeParser()
        parsed = parser.parse(resume["raw_text"])
        skill_master = parsed.skill_inventory_master_list

    bullet_texts = req.bullet_texts
    if not bullet_texts and resume.get("raw_text"):
        parser = ResumeParser()
        parsed = parser.parse(resume["raw_text"])
        bullet_texts = [
            b.text for e in parsed.experience for b in e.bullets
        ]

    if not bullet_texts:
        raise HTTPException(400, "No bullets to rewrite")

    jd_skills = req.jd_skills
    if not jd_skills:
        jd_skills = extract_skills(req.jd_text)

    # Use LLM rewriter
    rewriter = LLMRewriter()
    rr = RR(
        bullet_texts=bullet_texts,
        jd_text=req.jd_text,
        jd_skills=jd_skills,
        skill_inventory_master_list=skill_master,
    )
    rewrite_results = rewriter.rewrite_bullets(rr)
    validation_results = validate_all_rewrites(rewrite_results, skill_master)
    diff_report = generate_diff_report(rewrite_results, validation_results)
    gap_analysis = analyze_skill_gaps_v2(skill_master, jd_skills)

    resume_hash = hashlib.md5(
        (resume.get("raw_text", "") or "").encode()
    ).hexdigest()[:12]

    bullets_data = []
    for rr_item, vr in zip(rewrite_results, validation_results):
        bullets_data.append({
            "original_text": rr_item.original.text,
            "rewritten_text": rr_item.rewritten_text,
            "changes": rr_item.changes,
            "validation": {
                "word_count_ok": not any(e["rule"] == "word_count_delta" for e in vr.errors),
                "no_new_skills_ok": not any(e["rule"] == "no_new_skills" for e in vr.errors),
                "metrics_preserved_ok": not any(e["rule"] == "metrics_preserved" for e in vr.errors),
                "semantic_similarity_score": _get_similarity(vr),
                "action_verb_ok": not any(e["rule"] == "action_verb" for e in vr.warnings),
                "platform_swap_ok": not any(e["rule"] == "no_platform_swap" for e in vr.errors),
                "validation_passed": vr.passed,
                "errors": [e["message"] for e in vr.errors],
            },
        })

    variant = save_variant(
        parent_resume_id=req.resume_id,
        jd_title=req.jd_title,
        jd_company=req.jd_company,
        jd_text=req.jd_text,
        method="llm",
        bullets=bullets_data,
        diff_report=diff_report.to_dict(),
        gap_analysis=gap_analysis,
        jd_skills=jd_skills,
        jd_cleaned_text=req.jd_text[:2000],
        resume_hash=resume_hash,
        match_score=gap_analysis.get("match_rate", 0.0),
        weighted_score=gap_analysis.get("weighted_score", 0.0),
        coverage_rate=gap_analysis.get("coverage_rate", 0.0),
        exact_match_count=len(gap_analysis.get("exact_matches", [])),
        transferable_count=len(gap_analysis.get("transferable", [])),
        gap_count=len(gap_analysis.get("gaps", [])),
        validation_pass_rate=diff_report.validation_pass_rate,
    )

    return {
        "variant": variant,
        "diff_report": diff_report.to_dict(),
        "gap_analysis": gap_analysis,
        "rewrite_count": diff_report.changed_bullets,
        "total_bullets": diff_report.total_bullets,
    }


@router.get("/variants")
def list_variants(resume_id: str | None = None, status: str | None = None):
    """List all variants, optionally filtered."""
    from src.ml.variant_store import list_variants as _list
    return {"variants": _list(parent_resume_id=resume_id, status=status)}


@router.get("/variants/{variant_id}")
def get_variant(variant_id: str):
    """Get a variant with all bullet details and validation."""
    from src.ml.variant_store import get_variant as _get
    variant = _get(variant_id)
    if not variant:
        raise HTTPException(404, f"Variant '{variant_id}' not found")
    return variant


@router.delete("/variants/{variant_id}")
def delete_variant(variant_id: str):
    """Delete a variant (original resume is NEVER deleted)."""
    from src.ml.variant_store import delete_variant as _del
    if not _del(variant_id):
        raise HTTPException(404, f"Variant '{variant_id}' not found")
    return {"deleted": variant_id}


@router.patch("/variants/{variant_id}/bullet/{bullet_idx}")
def approve_bullet(variant_id: str, bullet_idx: int, req: BulletApprovalRequest):
    """Approve, reject, or edit a specific bullet in a variant."""
    from src.ml.variant_store import update_bullet_approval
    if req.approval not in ("approved", "rejected", "pending"):
        raise HTTPException(400, "approval must be 'approved', 'rejected', or 'pending'")
    ok = update_bullet_approval(
        variant_id, bullet_idx, req.approval, req.user_edited_text
    )
    if not ok:
        raise HTTPException(404, f"Bullet {bullet_idx} not found in variant {variant_id}")
    return {"variant_id": variant_id, "bullet_index": bullet_idx, "approval": req.approval}


@router.post("/variants/{variant_id}/finalize")
def finalize_variant(variant_id: str):
    """Finalize a variant — all bullets must be reviewed.

    approved → use rewritten text
    rejected → keep original text
    pending  → blocks finalization
    """
    from src.ml.variant_store import finalize_variant as _finalize
    result = _finalize(variant_id)
    if not result:
        raise HTTPException(404, f"Variant '{variant_id}' not found")
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/variants/{variant_id}/transition")
def transition_variant_status(variant_id: str, req: StatusTransitionRequest):
    """Transition variant to a new status (state machine enforced)."""
    from src.ml.variant_store import transition_status
    ok = transition_status(variant_id, req.new_status)
    if not ok:
        raise HTTPException(
            400,
            f"Invalid status transition to '{req.new_status}' for variant {variant_id}",
        )
    return {"variant_id": variant_id, "new_status": req.new_status}


@router.post("/variants/{variant_id}/interview")
def mark_interview(variant_id: str):
    """Mark that this variant got an interview callback."""
    from src.ml.variant_store import mark_interview_callback
    if not mark_interview_callback(variant_id):
        raise HTTPException(404, f"Variant '{variant_id}' not found")
    return {"variant_id": variant_id, "interview_callback": True}


@router.get("/stats")
def get_stats():
    """Get variant stats + bullet analytics for the dashboard."""
    from src.ml.variant_store import get_variant_stats
    return get_variant_stats()


@router.post("/skill-transfer")
def check_skill_transfer(req: SkillTransferRequest):
    """Check transferability between two skills with computed scoring."""
    from src.ml.skill_registry import compute_transfer
    result = compute_transfer(req.source_skill, req.target_skill)
    return result.to_dict()


@router.post("/gap-analysis")
def run_gap_analysis(req: GapAnalysisRequest):
    """Run full skill gap analysis with computed per-skill transfer scores."""
    from src.ml.skill_registry import analyze_skill_gaps_v2
    return analyze_skill_gaps_v2(req.resume_skills, req.jd_skills)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_similarity(vr) -> float:
    """Extract semantic similarity from validation result."""
    for err in vr.errors + vr.warnings:
        if err.get("rule") == "semantic_similarity":
            msg = err.get("message", "")
            # Parse "similarity: 0.XX" from message
            if "similarity:" in msg:
                try:
                    return float(msg.split("similarity:")[1].split(",")[0].strip())
                except (ValueError, IndexError):
                    pass
    return 1.0  # Default: no similarity issue means high similarity
