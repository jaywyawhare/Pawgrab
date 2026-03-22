"""Multi-provider LLM abstraction for structured extraction."""

from __future__ import annotations

from typing import Any

import orjson
import structlog

from pawgrab.config import settings

logger = structlog.get_logger()


class LLMProvider:
    """Base class for LLM providers."""

    async def extract(self, content: str, prompt: str, schema_hint: dict | None = None, json_schema: dict | None = None) -> dict[str, Any]:
        raise NotImplementedError


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self._api_key = api_key or settings.anthropic_api_key
        self._model = model or settings.anthropic_model
        self._client = None

    def _get_client(self):
        if self._client is None:
            from anthropic import AsyncAnthropic
            self._client = AsyncAnthropic(api_key=self._api_key)
        return self._client

    async def extract(self, content: str, prompt: str, schema_hint: dict | None = None, json_schema: dict | None = None) -> dict[str, Any]:
        from pawgrab.ai.prompts import SYSTEM_PROMPT, build_extraction_prompt
        user_message = build_extraction_prompt(content, prompt, schema_hint)
        if len(user_message) > 100_000:
            user_message = user_message[:100_000] + "\n\n[Content truncated]"

        try:
            response = await self._get_client().messages.create(
                model=self._model,
                max_tokens=4096,
                system=SYSTEM_PROMPT + "\n\nRespond ONLY with valid JSON.",
                messages=[{"role": "user", "content": user_message}],
                temperature=0,
            )
            raw = response.content[0].text
            try:
                return orjson.loads(raw)
            except orjson.JSONDecodeError:
                logger.warning("anthropic_json_parse_failed", raw_preview=raw[:200])
                return {"raw_response": raw}
        except orjson.JSONDecodeError:
            raise  # already handled above
        except Exception as exc:
            logger.error("anthropic_api_error", error=str(exc))
            raise RuntimeError(f"Anthropic API error: {exc}") from exc


class GeminiProvider(LLMProvider):
    """Google Gemini provider."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self._api_key = api_key or settings.gemini_api_key
        self._model = model or settings.gemini_model
        self._client = None

    def _get_client(self):
        if self._client is None:
            import google.generativeai as genai
            genai.configure(api_key=self._api_key)
            self._client = genai.GenerativeModel(self._model)
        return self._client

    async def extract(self, content: str, prompt: str, schema_hint: dict | None = None, json_schema: dict | None = None) -> dict[str, Any]:
        from pawgrab.ai.prompts import SYSTEM_PROMPT, build_extraction_prompt
        import asyncio
        user_message = build_extraction_prompt(content, prompt, schema_hint)
        if len(user_message) > 100_000:
            user_message = user_message[:100_000] + "\n\n[Content truncated]"

        full_prompt = f"{SYSTEM_PROMPT}\n\nRespond ONLY with valid JSON.\n\n{user_message}"

        try:
            model = self._get_client()
            response = await asyncio.to_thread(
                model.generate_content,
                full_prompt,
                generation_config={"temperature": 0, "response_mime_type": "application/json"},
            )
            raw = response.text
            return orjson.loads(raw)
        except Exception as exc:
            logger.error("gemini_api_error", error=str(exc))
            raise RuntimeError(f"Gemini API error: {exc}") from exc


class OllamaProvider(LLMProvider):
    """Local Ollama provider for self-hosted models."""

    def __init__(self, base_url: str | None = None, model: str | None = None):
        self._base_url = base_url or settings.ollama_base_url
        self._model = model or settings.ollama_model

    async def extract(self, content: str, prompt: str, schema_hint: dict | None = None, json_schema: dict | None = None) -> dict[str, Any]:
        from pawgrab.ai.prompts import SYSTEM_PROMPT, build_extraction_prompt
        user_message = build_extraction_prompt(content, prompt, schema_hint)
        if len(user_message) > 50_000:
            user_message = user_message[:50_000] + "\n\n[Content truncated]"

        try:
            from curl_cffi.requests import AsyncSession
            async with AsyncSession() as session:
                resp = await session.post(
                    f"{self._base_url}/api/chat",
                    json={
                        "model": self._model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT + "\n\nRespond ONLY with valid JSON."},
                            {"role": "user", "content": user_message},
                        ],
                        "format": "json",
                        "stream": False,
                        "options": {"temperature": 0},
                    },
                    timeout=120,
                )
                result = resp.json()
                raw = result.get("message", {}).get("content", "{}")
                return orjson.loads(raw)
        except Exception as exc:
            logger.error("ollama_api_error", error=str(exc))
            raise RuntimeError(f"Ollama API error: {exc}") from exc


def get_llm_provider(provider: str | None = None) -> LLMProvider:
    """Get the configured LLM provider."""
    provider = provider or settings.llm_provider

    if provider == "anthropic":
        return AnthropicProvider()
    elif provider == "gemini":
        return GeminiProvider()
    elif provider == "ollama":
        return OllamaProvider()
    else:
        # Default to OpenAI
        from pawgrab.ai.openai_provider import OpenAIProvider
        return OpenAIProvider()
