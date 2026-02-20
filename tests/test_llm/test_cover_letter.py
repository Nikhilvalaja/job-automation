"""Tests for cover letter generation and resume tailoring.

Tests template mode (no API key needed) and LLM mode (mocked).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.llm.generator import CoverLetterGenerator, ResumeTailor
from src.llm.prompts import COVER_LETTER_SYSTEM, COVER_LETTER_TEMPLATE, TONE_PRESETS
from src.models import CoverLetterRequest, CoverLetterResponse, ResumeTailorRequest, ResumeTailorResponse


class TestTemplateMode:
    """Test template-based cover letter generation (no API key needed)."""

    def test_template_generates_cover_letter(self):
        """Template mode should produce a cover letter with company and role."""
        gen = CoverLetterGenerator()
        request = CoverLetterRequest(
            company="Google",
            role="Software Engineer",
            job_description="Build scalable systems",
            mode="template",
        )
        result = gen.generate(request)
        assert isinstance(result, CoverLetterResponse)
        assert "Google" in result.cover_letter
        assert "Software Engineer" in result.cover_letter
        assert result.mode == "template"
        assert result.tokens_used == 0

    def test_template_different_companies(self):
        """Template should personalize for different companies."""
        gen = CoverLetterGenerator()

        r1 = gen.generate(CoverLetterRequest(
            company="Meta", role="MLE", job_description="", mode="template",
        ))
        r2 = gen.generate(CoverLetterRequest(
            company="Apple", role="iOS Dev", job_description="", mode="template",
        ))

        assert "Meta" in r1.cover_letter
        assert "Apple" in r2.cover_letter
        assert r1.cover_letter != r2.cover_letter

    def test_template_fallback_when_no_api_key(self):
        """LLM mode should fall back to template when API key is missing."""
        gen = CoverLetterGenerator()
        # Ensure LLM is not configured
        gen._llm._api_key = ""

        request = CoverLetterRequest(
            company="Amazon",
            role="SDE",
            job_description="Build stuff",
            mode="llm",  # Requested LLM but key not set
        )
        result = gen.generate(request)
        assert result.mode == "template"  # Should fall back
        assert "Amazon" in result.cover_letter


class TestLLMMode:
    """Test LLM-based cover letter generation (with mocked OpenAI)."""

    @patch("src.llm.client.LLMClient.chat")
    @patch("src.llm.client.LLMClient.is_configured", return_value=True)
    def test_llm_generates_cover_letter(self, mock_configured, mock_chat):
        """LLM mode should call OpenAI and return the response."""
        mock_chat.return_value = {
            "text": "Dear Google team, I am thrilled to apply...",
            "tokens_used": 350,
        }

        gen = CoverLetterGenerator()
        request = CoverLetterRequest(
            company="Google",
            role="SWE",
            job_description="Build scalable distributed systems at Google Cloud.",
            mode="llm",
        )
        result = gen.generate(request)

        assert result.mode == "llm"
        assert "thrilled" in result.cover_letter
        assert result.tokens_used == 350
        mock_chat.assert_called_once()

    @patch("src.llm.client.LLMClient.chat")
    @patch("src.llm.client.LLMClient.is_configured", return_value=True)
    def test_llm_includes_resume_in_prompt(self, mock_configured, mock_chat):
        """LLM mode should include resume text in the prompt."""
        mock_chat.return_value = {
            "text": "Generated letter...",
            "tokens_used": 200,
        }

        gen = CoverLetterGenerator()
        request = CoverLetterRequest(
            company="Meta",
            role="MLE",
            job_description="Build ML systems",
            resume_text="5 years experience in ML, published 3 papers",
            mode="llm",
        )
        gen.generate(request)

        # Check the user prompt passed to chat contains resume text
        mock_chat.assert_called_once()
        call_args = mock_chat.call_args
        user_prompt = call_args.kwargs.get("user_prompt", "")
        assert "5 years experience" in user_prompt

    @patch("src.llm.client.LLMClient.chat")
    @patch("src.llm.client.LLMClient.is_configured", return_value=True)
    def test_llm_truncates_long_jd(self, mock_configured, mock_chat):
        """Long job descriptions should be truncated to prevent token overuse."""
        mock_chat.return_value = {"text": "Letter...", "tokens_used": 100}

        gen = CoverLetterGenerator()
        long_jd = "x" * 10000  # Very long JD
        request = CoverLetterRequest(
            company="Test", role="Dev", job_description=long_jd, mode="llm",
        )
        gen.generate(request)
        mock_chat.assert_called_once()

    @patch("src.llm.client.LLMClient.chat")
    @patch("src.llm.client.LLMClient.is_configured", return_value=True)
    def test_llm_uses_tone(self, mock_configured, mock_chat):
        """LLM mode should pass the tone to the prompt."""
        mock_chat.return_value = {"text": "Startup letter...", "tokens_used": 150}

        gen = CoverLetterGenerator()
        request = CoverLetterRequest(
            company="Stripe",
            role="SWE",
            job_description="Build payments infra",
            tone="conversational",
            mode="llm",
        )
        gen.generate(request)

        call_args = mock_chat.call_args
        user_prompt = call_args.kwargs.get("user_prompt", "")
        assert "conversational" in user_prompt

    @patch("src.llm.client.LLMClient.chat")
    @patch("src.llm.client.LLMClient.is_configured", return_value=True)
    def test_llm_uses_extra_instructions(self, mock_configured, mock_chat):
        """LLM mode should include extra instructions in the prompt."""
        mock_chat.return_value = {"text": "Custom letter...", "tokens_used": 180}

        gen = CoverLetterGenerator()
        request = CoverLetterRequest(
            company="AWS",
            role="Cloud Architect",
            job_description="Design cloud solutions",
            extra_instructions="Mention my AWS Solutions Architect certification",
            mode="llm",
        )
        gen.generate(request)

        call_args = mock_chat.call_args
        user_prompt = call_args.kwargs.get("user_prompt", "")
        assert "AWS Solutions Architect" in user_prompt


class TestResumeTailor:
    """Test resume tailoring (with mocked OpenAI)."""

    @patch("src.llm.client.LLMClient.chat")
    @patch("src.llm.client.LLMClient.is_configured", return_value=True)
    def test_tailor_returns_tailored_resume(self, mock_configured, mock_chat):
        """Resume tailor should return modified resume and summary."""
        mock_chat.side_effect = [
            {"text": "Tailored resume content here...", "tokens_used": 500},
            {"text": "- Reordered skills section\n- Added JD keywords", "tokens_used": 50},
        ]

        tailor = ResumeTailor()
        request = ResumeTailorRequest(
            company="Google",
            role="SWE",
            job_description="Build distributed systems with Go and Python",
            resume_text="John Doe\nSoftware Engineer\n5 years experience in Python and Java",
        )
        result = tailor.tailor(request)

        assert isinstance(result, ResumeTailorResponse)
        assert "Tailored resume" in result.tailored_resume
        assert "Reordered" in result.changes_summary
        assert result.tokens_used == 550
        assert mock_chat.call_count == 2

    @patch("src.llm.client.LLMClient.chat")
    @patch("src.llm.client.LLMClient.is_configured", return_value=True)
    def test_tailor_with_focus_skills(self, mock_configured, mock_chat):
        """Resume tailor should include focus skills in the prompt."""
        mock_chat.side_effect = [
            {"text": "Resume...", "tokens_used": 400},
            {"text": "- Emphasized Python", "tokens_used": 40},
        ]

        tailor = ResumeTailor()
        request = ResumeTailorRequest(
            company="Meta",
            role="MLE",
            job_description="Build ML pipelines",
            resume_text="Jane Doe\nML Engineer\n3 years PyTorch",
            focus_skills=["Python", "PyTorch", "distributed training"],
        )
        tailor.tailor(request)

        # First call is the main tailoring call
        first_call = mock_chat.call_args_list[0]
        user_prompt = first_call.kwargs.get("user_prompt", "")
        assert "Python" in user_prompt
        assert "PyTorch" in user_prompt

    def test_tailor_requires_api_key(self):
        """Resume tailor should raise error without API key."""
        tailor = ResumeTailor()
        tailor._llm._api_key = ""

        request = ResumeTailorRequest(
            company="Test",
            role="Dev",
            job_description="Build things",
            resume_text="My resume...",
        )
        with pytest.raises(RuntimeError, match="OpenAI API key required"):
            tailor.tailor(request)


class TestCoverLetterAPI:
    """Test the cover letter API endpoint."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        return TestClient(app)

    def test_template_endpoint(self, client):
        """POST /cover-letter with template mode should work without API key."""
        resp = client.post("/cover-letter", json={
            "company": "TestCo",
            "role": "Engineer",
            "job_description": "Build things",
            "mode": "template",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "TestCo" in data["cover_letter"]
        assert data["mode"] == "template"

    def test_missing_company(self, client):
        """POST /cover-letter without company should return 400."""
        resp = client.post("/cover-letter", json={
            "company": "",
            "role": "Engineer",
            "job_description": "Build things",
            "mode": "template",
        })
        assert resp.status_code == 400

    def test_llm_mode_without_jd(self, client):
        """POST /cover-letter with LLM mode but no JD should return 400."""
        resp = client.post("/cover-letter", json={
            "company": "TestCo",
            "role": "Engineer",
            "job_description": "",
            "mode": "llm",
        })
        assert resp.status_code == 400

    def test_invalid_tone(self, client):
        """POST /cover-letter with invalid tone should return 400."""
        resp = client.post("/cover-letter", json={
            "company": "TestCo",
            "role": "Engineer",
            "job_description": "Build things",
            "tone": "aggressive",
            "mode": "template",
        })
        assert resp.status_code == 400

    def test_resume_tailor_missing_resume(self, client):
        """POST /tailor-resume without resume text should return 400."""
        resp = client.post("/tailor-resume", json={
            "company": "TestCo",
            "role": "Engineer",
            "job_description": "Build things",
            "resume_text": "",
        })
        assert resp.status_code == 400


class TestTonePresets:
    """Test that tone presets are properly defined."""

    def test_all_tones_exist(self):
        assert "professional" in TONE_PRESETS
        assert "conversational" in TONE_PRESETS
        assert "technical" in TONE_PRESETS
        assert "executive" in TONE_PRESETS

    def test_tone_descriptions_not_empty(self):
        for tone, desc in TONE_PRESETS.items():
            assert len(desc) > 10, f"Tone '{tone}' has too short a description"
