"""Cover letter generation API endpoint.

POST /cover-letter — Generate a tailored cover letter for a job application.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.llm.generator import CoverLetterGenerator
from src.models import CoverLetterRequest, CoverLetterResponse

router = APIRouter(tags=["cover-letter"])

_generator: CoverLetterGenerator | None = None


def get_generator() -> CoverLetterGenerator:
    """Lazy singleton for the cover letter generator."""
    global _generator
    if _generator is None:
        _generator = CoverLetterGenerator()
    return _generator


@router.post("/cover-letter", response_model=CoverLetterResponse)
async def generate_cover_letter(request: CoverLetterRequest) -> CoverLetterResponse:
    """Generate a cover letter for a job application.

    Modes:
    - "llm": Uses OpenAI GPT (requires OPENAI_API_KEY in .env)
    - "template": Uses a basic template (no API key needed)
    """
    if not request.company or not request.role:
        raise HTTPException(status_code=400, detail="Company and role are required")

    if not request.job_description and request.mode == "llm":
        raise HTTPException(
            status_code=400,
            detail="Job description is required for LLM mode",
        )

    try:
        generator = get_generator()
        result = generator.generate(request)
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")
