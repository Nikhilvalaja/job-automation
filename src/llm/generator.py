"""Cover letter generator — produces tailored cover letters via LLM or template.

Supports two modes:
- "llm": Uses OpenAI GPT to generate a personalized cover letter
- "template": Uses a simple template (no API key needed, good for testing)

SAFETY: Never stores generated cover letters. Only returns them to the caller.
"""

from __future__ import annotations

from src.llm.client import LLMClient
from src.llm.prompts import (
    COVER_LETTER_SYSTEM,
    COVER_LETTER_TEMPLATE,
    COVER_LETTER_USER,
)
from src.models import CoverLetterRequest, CoverLetterResponse
from src.utils.logging import get_logger

logger = get_logger(__name__)


class CoverLetterGenerator:
    """Generates cover letters using LLM or template fallback."""

    def __init__(self) -> None:
        self._llm = LLMClient()

    def generate(self, request: CoverLetterRequest) -> CoverLetterResponse:
        """Generate a cover letter based on the request.

        If mode is "llm" and OpenAI is configured, uses GPT.
        Falls back to template mode if API key is missing.
        """
        if request.mode == "llm" and self._llm.is_configured():
            return self._generate_llm(request)
        else:
            if request.mode == "llm" and not self._llm.is_configured():
                logger.warning("OpenAI not configured — falling back to template mode")
            return self._generate_template(request)

    def _generate_llm(self, request: CoverLetterRequest) -> CoverLetterResponse:
        """Generate using OpenAI GPT."""
        resume_section = ""
        if request.resume_text:
            # Limit resume text to avoid token overuse
            trimmed = request.resume_text[:3000]
            resume_section = f"**Applicant's Resume/Background:**\n{trimmed}"

        user_prompt = COVER_LETTER_USER.format(
            company=request.company,
            role=request.role,
            job_description=request.job_description[:4000],
            resume_section=resume_section,
        )

        result = self._llm.chat(
            system_prompt=COVER_LETTER_SYSTEM,
            user_prompt=user_prompt,
            temperature=0.7,
            max_tokens=1500,
        )

        logger.info(f"Generated cover letter for {request.company}/{request.role} via LLM")

        return CoverLetterResponse(
            cover_letter=result["text"],
            mode="llm",
            tokens_used=result["tokens_used"],
        )

    def _generate_template(self, request: CoverLetterRequest) -> CoverLetterResponse:
        """Generate using simple template (no API needed)."""
        cover_letter = COVER_LETTER_TEMPLATE.format(
            company=request.company,
            role=request.role,
        )

        logger.info(f"Generated cover letter for {request.company}/{request.role} via template")

        return CoverLetterResponse(
            cover_letter=cover_letter,
            mode="template",
            tokens_used=0,
        )
