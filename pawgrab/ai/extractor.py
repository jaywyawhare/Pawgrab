"""Fetch a URL, clean it, and extract structured data via OpenAI."""

from __future__ import annotations

from typing import Any

import structlog

from pawgrab.engine.cleaner import extract_content
from pawgrab.engine.converter import html_to_markdown
from pawgrab.engine.fetcher import fetch_page
from pawgrab.utils.rate_limiter import guard_url

logger = structlog.get_logger()

_provider = None


def get_provider():
    """Get or create the LLM provider based on configuration."""
    global _provider
    if _provider is None:
        from pawgrab.ai.providers import get_llm_provider

        _provider = get_llm_provider()
    return _provider


async def extract_from_url(
    url: str,
    prompt: str,
    schema_hint: dict[str, Any] | None = None,
    json_schema: dict[str, Any] | None = None,
    timeout: int = 30_000,
    browser_pool: object | None = None,
    chunk_strategy: str | None = None,
    chunk_size: int = 4000,
    chunk_overlap: int = 200,
) -> dict[str, Any]:
    """Full pipeline: fetch → clean → markdown → (chunk) → LLM extraction."""
    await guard_url(url)
    result = await fetch_page(url, timeout=timeout, browser_pool=browser_pool)
    cleaned = extract_content(result.html, url=result.url)
    markdown = html_to_markdown(cleaned.content_html)

    provider = get_provider()

    if chunk_strategy:
        return await _chunked_extract(
            markdown,
            prompt,
            provider,
            schema_hint=schema_hint,
            json_schema=json_schema,
            chunk_strategy=chunk_strategy,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    return await provider.extract(markdown, prompt, schema_hint, json_schema=json_schema)


async def _chunked_extract(
    markdown: str,
    prompt: str,
    provider,
    *,
    schema_hint: dict[str, Any] | None = None,
    json_schema: dict[str, Any] | None = None,
    chunk_strategy: str = "fixed",
    chunk_size: int = 4000,
    chunk_overlap: int = 200,
) -> dict[str, Any]:
    """Extract from large content by chunking, extracting each chunk, then merging."""
    from pawgrab.ai.chunking import get_chunker

    chunker = get_chunker(chunk_strategy, chunk_size=chunk_size, overlap=chunk_overlap)
    chunks = chunker.chunk(markdown)

    if len(chunks) <= 1:
        return await provider.extract(markdown, prompt, schema_hint, json_schema=json_schema)

    logger.info("chunked_extraction", num_chunks=len(chunks), strategy=chunk_strategy)

    results: list[dict[str, Any]] = []
    for i, chunk in enumerate(chunks):
        try:
            result = await provider.extract(chunk, prompt, schema_hint, json_schema=json_schema)
            results.append(result)
        except Exception as exc:
            logger.warning("chunk_extraction_failed", chunk=i, error=str(exc))

    if not results:
        return {}

    return _merge_results(results)


def _merge_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge extraction results from multiple chunks.

    Strategy:
      - For list values: concatenate and deduplicate
      - For scalar values: keep the first non-null value
      - For dict values: merge recursively
    """
    if len(results) == 1:
        return results[0]

    merged: dict[str, Any] = {}
    for result in results:
        for key, value in result.items():
            if key not in merged:
                merged[key] = value
            elif isinstance(value, list) and isinstance(merged[key], list):
                seen = set()
                combined = []
                for item in merged[key] + value:
                    item_key = str(item)
                    if item_key not in seen:
                        seen.add(item_key)
                        combined.append(item)
                merged[key] = combined
            elif isinstance(value, dict) and isinstance(merged[key], dict):
                for dk, dv in value.items():
                    if dk not in merged[key] or merged[key][dk] is None:
                        merged[key][dk] = dv
            elif merged[key] is None and value is not None:
                merged[key] = value

    return merged
