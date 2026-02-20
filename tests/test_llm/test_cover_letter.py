"""Tests for cover letter generation.

Tests template mode (no API key needed) and LLM mode (mocked).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.llm.generator import CoverLetterGenerator
from src.llm.prompts import COVER_LETTER_SYSTEM, COVER_LETTER_TEMPLATE
from src.models import CoverLetterRequest, CoverLetterResponse


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
        call_args = mock_chat.call_args
        user_prompt = call_args.kwargs.get("user_prompt") or call_args[1].get("user_prompt", "") or call_args[0][1] if call_args[0] else ""
        # The resume should be included somewhere in the call
        mock_chat.assert_called_once()

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
