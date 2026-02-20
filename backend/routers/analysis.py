"""Analysis API — resume management, JD scoring, and DB health.

Endpoints:
- POST /analysis/resumes/upload   — Upload + parse a resume
- GET  /analysis/resumes          — List all resumes
- GET  /analysis/resumes/{id}     — Get a resume with full parsed data
- DELETE /analysis/resumes/{id}   — Delete a resume
- PATCH /analysis/resumes/{id}/default — Set as default resume
- POST /analysis/normalize-jd     — Normalize a job description
- POST /analysis/score            — Score a resume against a JD
- GET  /analysis/health           — DB health (backup, retention, counts)
- GET  /analysis/suggest-resume   — Suggest best resume for a JD
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/analysis", tags=["analysis"])


# --- Request / Response Models ---

class ResumeUploadRequest(BaseModel):
    name: str
    raw_text: str
    is_default: bool = False


class NormalizeJDRequest(BaseModel):
    title: str
    description: str
    location: str = ""


class ScoreRequest(BaseModel):
    resume_id: str
    title: str
    description: str
    location: str = ""


class ScoreByTextRequest(BaseModel):
    resume_text: str
    title: str
    description: str
    location: str = ""


# --- Resume CRUD ---

@router.post("/resumes/upload")
async def upload_resume(body: ResumeUploadRequest):
    """Upload a resume, parse it, and store it."""
    from src.ml.resume_parser import ResumeParser
    from src.ml.resume_store import save_resume

    if not body.raw_text.strip():
        raise HTTPException(status_code=400, detail="Resume text cannot be empty")

    parser = ResumeParser()
    parsed = parser.parse(body.raw_text)

    record = save_resume(
        name=body.name,
        raw_text=body.raw_text,
        parsed_json=parsed.to_dict(),
        skill_inventory=parsed.skill_inventory_master_list,
        skill_categories=parsed.skill_categories,
        total_bullets=parsed.total_bullets,
        total_metrics=parsed.total_metrics,
        is_default=body.is_default,
    )
    return record


@router.get("/resumes")
async def list_all_resumes():
    """List all uploaded resumes."""
    from src.ml.resume_store import list_resumes
    return {"resumes": list_resumes()}


@router.get("/resumes/{resume_id}")
async def get_resume_detail(resume_id: str):
    """Get a resume with full parsed data."""
    from src.ml.resume_store import get_resume
    record = get_resume(resume_id)
    if not record:
        raise HTTPException(status_code=404, detail="Resume not found")
    return record


@router.delete("/resumes/{resume_id}")
async def delete_resume_endpoint(resume_id: str):
    """Delete a resume."""
    from src.ml.resume_store import delete_resume
    if not delete_resume(resume_id):
        raise HTTPException(status_code=404, detail="Resume not found")
    return {"ok": True, "deleted": resume_id}


@router.patch("/resumes/{resume_id}/default")
async def set_default_resume_endpoint(resume_id: str):
    """Set a resume as the default."""
    from src.ml.resume_store import set_default_resume
    if not set_default_resume(resume_id):
        raise HTTPException(status_code=404, detail="Resume not found")
    return {"ok": True, "default": resume_id}


# --- JD Normalization ---

@router.post("/normalize-jd")
async def normalize_jd(body: NormalizeJDRequest):
    """Normalize a job description — extract skills, classify, clean."""
    from src.ml.jd_normalizer import JDNormalizer

    normalizer = JDNormalizer()
    result = normalizer.normalize(body.title, body.description, body.location)
    return result.to_dict()


# --- Scoring ---

@router.post("/score")
async def score_resume(body: ScoreRequest):
    """Score a stored resume against a job description."""
    from src.ml.jd_normalizer import JDNormalizer
    from src.ml.resume_parser import ResumeParser
    from src.ml.resume_store import get_resume
    from src.ml.scorer import ResumeScorer
    from src.ml.embeddings import EmbeddingService

    record = get_resume(body.resume_id)
    if not record:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Normalize the JD
    normalizer = JDNormalizer()
    jd = normalizer.normalize(body.title, body.description, body.location)

    # Parse the resume from stored text
    parser = ResumeParser()
    resume = parser.parse(record["raw_text"])

    # Score
    embedding_svc = EmbeddingService()
    scorer = ResumeScorer(embedding_service=embedding_svc)
    result = scorer.score(jd, resume)

    return result.to_dict()


@router.post("/score-text")
async def score_resume_text(body: ScoreByTextRequest):
    """Score raw resume text against a job description (no stored resume needed)."""
    from src.ml.jd_normalizer import JDNormalizer
    from src.ml.resume_parser import ResumeParser
    from src.ml.scorer import ResumeScorer
    from src.ml.embeddings import EmbeddingService

    normalizer = JDNormalizer()
    jd = normalizer.normalize(body.title, body.description, body.location)

    parser = ResumeParser()
    resume = parser.parse(body.resume_text)

    embedding_svc = EmbeddingService()
    scorer = ResumeScorer(embedding_service=embedding_svc)
    result = scorer.score(jd, resume)

    return result.to_dict()


# --- Resume Suggestion ---

@router.post("/suggest-resume")
async def suggest_best_resume(body: NormalizeJDRequest):
    """Score all stored resumes against a JD and return the best match."""
    from src.ml.jd_normalizer import JDNormalizer
    from src.ml.resume_parser import ResumeParser
    from src.ml.resume_store import list_resumes, get_resume
    from src.ml.scorer import ResumeScorer
    from src.ml.embeddings import EmbeddingService

    resumes = list_resumes()
    if not resumes:
        return {"suggestion": None, "message": "No resumes uploaded yet"}

    normalizer = JDNormalizer()
    jd = normalizer.normalize(body.title, body.description, body.location)

    parser = ResumeParser()
    embedding_svc = EmbeddingService()
    scorer = ResumeScorer(embedding_service=embedding_svc)

    scores = []
    for r in resumes:
        full = get_resume(r["id"])
        if not full:
            continue
        parsed = parser.parse(full["raw_text"])
        result = scorer.score(jd, parsed)
        scores.append({
            "resume_id": r["id"],
            "resume_name": r["name"],
            "match_score": result.match_score,
            "must_have_coverage": result.must_have_coverage,
            "missing_must_haves": result.missing_must_haves,
            "matched_skills": result.matched_skills,
            "recommended_emphasis": result.recommended_emphasis,
        })

    scores.sort(key=lambda x: x["match_score"], reverse=True)
    return {
        "suggestion": scores[0] if scores else None,
        "all_scores": scores,
    }


# --- DB Health ---

@router.get("/health")
async def db_health():
    """Get health status of all databases — backup, retention, row counts."""
    from pathlib import Path
    from src.config import PROJECT_ROOT
    from src.ml.resume_store import get_resume_count

    health = {
        "discovery_db": _get_db_info(PROJECT_ROOT / "data" / "discovery.db"),
        "resumes_db": _get_db_info(PROJECT_ROOT / "data" / "resumes.db"),
        "resume_count": get_resume_count(),
    }

    # Backup health
    try:
        from src.utils.backup import get_backup_health
        backup_dir = PROJECT_ROOT / "data" / "backups"
        discovery_db = PROJECT_ROOT / "data" / "discovery.db"
        health["backup"] = get_backup_health(db_path=discovery_db, backup_dir=backup_dir)
    except Exception:
        health["backup"] = {"status": "unknown"}

    # Retention stats
    try:
        from src.utils.retention import get_retention_stats
        discovery_db = PROJECT_ROOT / "data" / "discovery.db"
        health["retention"] = get_retention_stats(db_path=discovery_db)
    except Exception:
        health["retention"] = {}

    return health


def _get_db_info(db_path) -> dict:
    """Get basic info about a SQLite database file."""
    from pathlib import Path
    p = Path(db_path)
    if not p.exists():
        return {"exists": False, "size_mb": 0}
    size_mb = p.stat().st_size / (1024 * 1024)
    return {"exists": True, "size_mb": round(size_mb, 2), "path": str(p.name)}
