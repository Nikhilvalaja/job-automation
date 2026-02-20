"""Cover letter & resume tailor API endpoints.

POST /cover-letter — Generate a tailored cover letter
POST /tailor-resume — Tailor a resume for a specific JD
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.llm.generator import CoverLetterGenerator, ResumeTailor
from src.models import (
    CoverLetterRequest,
    CoverLetterResponse,
    ResumeTailorRequest,
    ResumeTailorResponse,
)

router = APIRouter(tags=["ai-tools"])

_generator: CoverLetterGenerator | None = None
_tailor: ResumeTailor | None = None


def get_generator() -> CoverLetterGenerator:
    """Lazy singleton for the cover letter generator."""
    global _generator
    if _generator is None:
        _generator = CoverLetterGenerator()
    return _generator


def get_tailor() -> ResumeTailor:
    """Lazy singleton for the resume tailor."""
    global _tailor
    if _tailor is None:
        _tailor = ResumeTailor()
    return _tailor


@router.post("/cover-letter", response_model=CoverLetterResponse)
async def generate_cover_letter(request: CoverLetterRequest) -> CoverLetterResponse:
    """Generate a cover letter for a job application.

    Modes:
    - "llm": Uses OpenAI GPT (requires OPENAI_API_KEY in .env)
    - "template": Uses a basic template (no API key needed)

    Tones: professional, conversational, technical, executive
    """
    if not request.company or not request.role:
        raise HTTPException(status_code=400, detail="Company and role are required")

    if not request.job_description and request.mode == "llm":
        raise HTTPException(
            status_code=400,
            detail="Job description is required for LLM mode",
        )

    if request.tone not in ("professional", "conversational", "technical", "executive"):
        raise HTTPException(status_code=400, detail="Tone must be: professional, conversational, technical, or executive")

    try:
        generator = get_generator()
        result = generator.generate(request)
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")


@router.post("/tailor-resume", response_model=ResumeTailorResponse)
async def tailor_resume(request: ResumeTailorRequest) -> ResumeTailorResponse:
    """Tailor a resume for a specific job description.

    Requires OPENAI_API_KEY — no template fallback available.
    Restructures and optimizes the resume for ATS and relevance.
    """
    if not request.company or not request.role:
        raise HTTPException(status_code=400, detail="Company and role are required")

    if not request.job_description:
        raise HTTPException(status_code=400, detail="Job description is required")

    if not request.resume_text:
        raise HTTPException(status_code=400, detail="Resume text is required")

    try:
        tailor = get_tailor()
        result = tailor.tailor(request)
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Resume tailoring failed: {e}")
