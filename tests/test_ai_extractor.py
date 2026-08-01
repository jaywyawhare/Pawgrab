from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pawgrab.ai.extractor import _merge_results


class TestMergeResults:
    def test_single_result(self):
        assert _merge_results([{"name": "Alice", "age": 30}]) == {"name": "Alice", "age": 30}

    def test_list_values_concatenated_and_deduplicated(self):
        results = [{"items": ["a", "b"]}, {"items": ["b", "c"]}]
        merged = _merge_results(results)
        assert set(merged["items"]) == {"a", "b", "c"}
        assert merged["items"].count("b") == 1

    def test_scalar_first_non_null_wins(self):
        results = [{"title": None}, {"title": "Actual Title"}]
        assert _merge_results(results)["title"] == "Actual Title"

        results = [{"title": "First"}, {"title": "Second"}]
        assert _merge_results(results)["title"] == "First"

    def test_dict_values_merged(self):
        results = [
            {"meta": {"source": "web", "date": None}},
            {"meta": {"source": "other", "date": "2024-01-01"}},
        ]
        merged = _merge_results(results)["meta"]
        assert merged["source"] == "web"
        assert merged["date"] == "2024-01-01"

    def test_keys_from_multiple_results_combined(self):
        merged = _merge_results([{"a": 1}, {"b": 2}])
        assert merged["a"] == 1
        assert merged["b"] == 2

    def test_empty_dict_result(self):
        assert _merge_results([{}]) == {}


@pytest.mark.asyncio
class TestExtractFromUrl:
    async def test_basic_extraction_flow(self):
        from pawgrab.ai.extractor import extract_from_url
        from pawgrab.engine.cleaner import CleanedContent
        from pawgrab.engine.fetcher import FetchResult

        mock_fetch_result = FetchResult(
            html="<html><body><p>Content</p></body></html>",
            status_code=200,
            url="https://example.com",
        )
        mock_cleaned = MagicMock(spec=CleanedContent)
        mock_cleaned.content_html = "<p>Content</p>"
        mock_provider = AsyncMock()
        mock_provider.extract = AsyncMock(return_value={"title": "Test"})

        with (
            patch("pawgrab.ai.extractor.guard_url", new_callable=AsyncMock),
            patch("pawgrab.ai.extractor.fetch_page", new_callable=AsyncMock, return_value=mock_fetch_result),
            patch("pawgrab.ai.extractor.extract_content", return_value=mock_cleaned),
            patch("pawgrab.ai.extractor.get_provider", return_value=mock_provider),
        ):
            result = await extract_from_url("https://example.com", prompt="Extract title")

        assert result == {"title": "Test"}
        mock_provider.extract.assert_called_once()

    async def test_robots_blocked_raises(self):
        from pawgrab.ai.extractor import extract_from_url

        with patch("pawgrab.ai.extractor.guard_url", new_callable=AsyncMock, side_effect=PermissionError("blocked")):
            with pytest.raises(PermissionError):
                await extract_from_url("https://example.com", prompt="test")

    async def test_chunked_extraction(self):
        from pawgrab.ai.extractor import extract_from_url
        from pawgrab.engine.cleaner import CleanedContent
        from pawgrab.engine.fetcher import FetchResult

        mock_fetch_result = FetchResult(
            html="<html><body><p>Long content</p></body></html>",
            status_code=200,
            url="https://example.com",
        )
        mock_cleaned = MagicMock(spec=CleanedContent)
        mock_cleaned.content_html = "<p>" + "x " * 5000 + "</p>"
        mock_provider = AsyncMock()
        mock_provider.extract = AsyncMock(return_value={"data": "value"})

        with (
            patch("pawgrab.ai.extractor.guard_url", new_callable=AsyncMock),
            patch("pawgrab.ai.extractor.fetch_page", new_callable=AsyncMock, return_value=mock_fetch_result),
            patch("pawgrab.ai.extractor.extract_content", return_value=mock_cleaned),
            patch("pawgrab.ai.extractor.get_provider", return_value=mock_provider),
        ):
            result = await extract_from_url(
                "https://example.com",
                prompt="extract",
                chunk_strategy="fixed",
                chunk_size=100,
            )

        assert isinstance(result, dict)


async def test_chunk_cap_limits_llm_calls(monkeypatch):
    """A huge page must not fan out into unbounded LLM calls (H11)."""
    from unittest.mock import AsyncMock

    from pawgrab.ai import extractor as ext
    from pawgrab.config import settings

    monkeypatch.setattr(settings, "llm_max_chunks", 3)

    class _Chunker:
        def chunk(self, md):
            return [f"chunk{i}" for i in range(50)]

    monkeypatch.setattr("pawgrab.ai.chunking.get_chunker", lambda *a, **k: _Chunker())

    provider = AsyncMock()
    provider.extract = AsyncMock(return_value={"x": 1})

    await ext._chunked_extract("x" * 10000, "prompt", provider, chunk_strategy="fixed")
    # Only the capped number of chunks are sent to the LLM.
    assert provider.extract.await_count == 3
