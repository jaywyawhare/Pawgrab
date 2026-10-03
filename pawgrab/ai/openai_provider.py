"""OpenAI-based LLM provider for structured extraction."""

from __future__ import annotations

from typing import Any

import orjson
import structlog
from openai import APIError, AsyncOpenAI

from pawgrab.ai.prompts import SYSTEM_PROMPT, build_extraction_prompt
from pawgrab.config import settings

logger = structlog.get_logger()


class OpenAIProvider:
    __slots__ = ("_api_key", "_model", "_client")

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self._api_key = api_key or settings.openai_api_key
        self._model = model or settings.openai_model
        self._client = None

    def _get_client(self):
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self._api_key)
        return self._client

    async def extract(
        self,
        content: str,
        prompt: str,
        schema_hint: dict[str, Any] | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        user_message = build_extraction_prompt(content, prompt, schema_hint)
        if len(user_message) > 100_000:
            truncated = user_message[:100_000]
            last_break = truncated.rfind("\n\n")
            if last_break > 50_000:
                truncated = truncated[:last_break]
            user_message = truncated + "\n\n[Content truncated]"
        if json_schema:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "extraction_result",
                    "strict": True,
                    "schema": json_schema,
                },
            }
        else:
            response_format = {"type": "json_object"}
        try:
            response = await self._get_client().chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                response_format=response_format,
                temperature=0,
                max_tokens=settings.llm_max_output_tokens,
                timeout=60,
            )
        except APIError as exc:
            logger.error("openai_api_error", error=str(exc), status=getattr(exc, "status_code", None))
            raise RuntimeError(f"LLM API error: {exc}") from exc

        usage = getattr(response, "usage", None)
        if usage is not None:
            logger.info(
                "llm_usage",
                model=self._model,
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
            )
        raw = response.choices[0].message.content or "{}"
        try:
            parsed = orjson.loads(raw)
        except orjson.JSONDecodeError as exc:
            logger.warning("llm_json_parse_failed", raw=raw[:200])
            raise RuntimeError("LLM returned invalid JSON") from exc

        if json_schema:
            _validate_against_schema(parsed, json_schema)
        return parsed


def _validate_against_schema(data: Any, schema: dict[str, Any]) -> None:
    """Best-effort validation of top-level required keys/type for LLM output."""
    if schema.get("type") == "object" and isinstance(data, dict):
        missing = [k for k in schema.get("required", []) if k not in data]
        if missing:
            raise RuntimeError(f"LLM output missing required fields: {missing}")
