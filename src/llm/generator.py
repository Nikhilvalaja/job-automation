"""Cover letter & resume tailor — LLM-powered document generation.

Supports two modes for cover letters:
- "llm": Uses OpenAI GPT with advanced prompting (tone, structure, resume-aware)
- "template": Uses a simple template (no API key needed, good for testing)

Resume tailoring always requires LLM mode.

SAFETY: Never stores generated documents. Only returns them to the caller.
"""

from __future__ import annotations

from src.llm.client import LLMClient
from src.llm.prompts import (
    COVER_LETTER_SYSTEM,
    COVER_LETTER_TEMPLATE,
    COVER_LETTER_USER,
    RESUME_TAILOR_SYSTEM,
    RESUME_TAILOR_USER,
    TONE_PRESETS,
)
from src.models import (
    CoverLetterRequest,
    CoverLetterResponse,
    ResumeTailorRequest,
    ResumeTailorResponse,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)

MAX_JD_CHARS = 4000
MAX_RESUME_CHARS = 3000


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
        """Generate using OpenAI GPT with advanced prompting."""
        # Build resume section
        resume_section = ""
        if request.resume_text:
            trimmed = request.resume_text[:MAX_RESUME_CHARS]
            resume_section = f"**Applicant's Resume/Background:**\n{trimmed}"

        # Resolve tone description
        tone = request.tone or "professional"
        tone_desc = TONE_PRESETS.get(tone, TONE_PRESETS["professional"])
        tone_line = f"{tone} — {tone_desc}"

        # Build extra instructions
        extra = ""
        if request.extra_instructions:
            extra = f"**Additional Instructions:** {request.extra_instructions[:500]}"

        user_prompt = COVER_LETTER_USER.format(
            company=request.company,
            role=request.role,
            tone=tone_line,
            job_description=request.job_description[:MAX_JD_CHARS],
            resume_section=resume_section,
            extra_instructions=extra,
        )

        result = self._llm.chat(
            system_prompt=COVER_LETTER_SYSTEM,
            user_prompt=user_prompt,
            temperature=0.7,
            max_tokens=1500,
        )

        logger.info(f"Generated cover letter for {request.company}/{request.role} via LLM ({tone})")

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


class ResumeTailor:
    """Tailors resumes to match specific job descriptions using LLM."""

    def __init__(self) -> None:
        self._llm = LLMClient()

    def tailor(self, request: ResumeTailorRequest) -> ResumeTailorResponse:
        """Tailor a resume for a specific job description.

        Requires OpenAI to be configured — no template fallback.
        """
        if not self._llm.is_configured():
            raise RuntimeError("OpenAI API key required for resume tailoring. Set OPENAI_API_KEY in .env")

        # Build the user prompt
        jd_trimmed = request.job_description[:MAX_JD_CHARS]
        resume_trimmed = request.resume_text[:5000]  # resumes can be longer

        user_prompt = RESUME_TAILOR_USER.format(
            company=request.company,
            role=request.role,
            job_description=jd_trimmed,
            resume_text=resume_trimmed,
        )

        # If user specified focus skills, append them
        if request.focus_skills:
            skills_str = ", ".join(request.focus_skills[:10])
            user_prompt += f"\n\n**Priority skills to emphasize:** {skills_str}"

        result = self._llm.chat(
            system_prompt=RESUME_TAILOR_SYSTEM,
            user_prompt=user_prompt,
            temperature=0.4,  # lower creativity for resume — accuracy matters
            max_tokens=3000,  # resumes need more tokens
        )

        # Ask for a brief summary of changes made
        summary_result = self._llm.chat(
            system_prompt="You summarize resume changes in 2-3 bullet points. Be concise.",
            user_prompt=f"Original resume:\n{resume_trimmed[:1000]}\n\nTailored resume:\n{result['text'][:1000]}\n\nList the key changes made in 2-3 bullet points.",
            temperature=0.3,
            max_tokens=300,
        )

        total_tokens = result["tokens_used"] + summary_result["tokens_used"]

        logger.info(f"Tailored resume for {request.company}/{request.role} ({total_tokens} tokens)")

        return ResumeTailorResponse(
            tailored_resume=result["text"],
            changes_summary=summary_result["text"],
            tokens_used=total_tokens,
        )
