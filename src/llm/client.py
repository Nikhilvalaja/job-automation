"""OpenAI API client wrapper.

Provides a clean interface for calling OpenAI's chat completion API.
Supports retry logic, token tracking, and graceful fallback.

SAFETY: Never logs prompts or responses (may contain personal info).
Only logs token counts and error messages.
"""

from __future__ import annotations

from openai import OpenAI, APIError, RateLimitError

from src.config import get_settings
from src.utils.logging import get_logger
from src.utils.retry import retry

logger = get_logger(__name__)


class LLMClient:
    """Wrapper around OpenAI's chat completion API."""

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.openai_api_key
        self._model = settings.openai_model
        self._client: OpenAI | None = None

    def is_configured(self) -> bool:
        """Check if OpenAI API key is set."""
        return bool(self._api_key)

    @property
    def client(self) -> OpenAI:
        """Lazy-initialized OpenAI client."""
        if self._client is None:
            if not self.is_configured():
                raise RuntimeError("OpenAI API key not configured. Set OPENAI_API_KEY in .env")
            self._client = OpenAI(api_key=self._api_key)
        return self._client

    @retry(max_attempts=3, base_delay=2.0, exceptions=(APIError, RateLimitError))
    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> dict:
        """Send a chat completion request.

        Args:
            system_prompt: System message setting the AI's role.
            user_prompt: The user's request.
            temperature: Creativity (0.0 = deterministic, 1.0 = creative).
            max_tokens: Maximum response length.

        Returns:
            Dict with 'text' (response content) and 'tokens_used' (total tokens).
        """
        response = self.client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )

        text = response.choices[0].message.content or ""
        tokens = response.usage.total_tokens if response.usage else 0

        logger.info(f"LLM response: {tokens} tokens used (model={self._model})")
        return {"text": text, "tokens_used": tokens}
