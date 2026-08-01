from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pawgrab.ai.providers import (
    AnthropicProvider,
    GeminiProvider,
    LLMProvider,
    OllamaProvider,
    get_llm_provider,
)


class TestLLMProviderBase:
    @pytest.mark.asyncio
    async def test_base_extract_raises_not_implemented(self):
        with pytest.raises(NotImplementedError):
            await LLMProvider().extract("content", "prompt")


class TestGetLlmProvider:
    def test_returns_openai_by_default(self):
        with patch("pawgrab.ai.providers.settings") as mock_settings:
            mock_settings.llm_provider = "openai"
            mock_settings.llm_fallback_provider = ""
            mock_settings.llm_max_retries = 0
            with patch("pawgrab.ai.openai_provider.OpenAIProvider") as mock_cls:
                mock_cls.return_value = MagicMock()
                get_llm_provider()
        mock_cls.assert_called_once()

    def test_returns_anthropic_provider(self):
        with patch("pawgrab.ai.providers.settings") as mock_settings:
            mock_settings.llm_provider = "anthropic"
            mock_settings.anthropic_api_key = "key"
            mock_settings.anthropic_model = "claude-3"
            mock_settings.llm_fallback_provider = ""
            mock_settings.llm_max_retries = 0
            assert isinstance(get_llm_provider("anthropic"), AnthropicProvider)

    def test_returns_gemini_provider(self):
        with patch("pawgrab.ai.providers.settings") as mock_settings:
            mock_settings.llm_provider = "gemini"
            mock_settings.gemini_api_key = "gkey"
            mock_settings.gemini_model = "gemini-pro"
            mock_settings.llm_fallback_provider = ""
            mock_settings.llm_max_retries = 0
            assert isinstance(get_llm_provider("gemini"), GeminiProvider)

    def test_returns_ollama_provider(self):
        with patch("pawgrab.ai.providers.settings") as mock_settings:
            mock_settings.llm_provider = "ollama"
            mock_settings.ollama_base_url = "http://localhost:11434"
            mock_settings.ollama_model = "llama3"
            mock_settings.llm_fallback_provider = ""
            mock_settings.llm_max_retries = 0
            assert isinstance(get_llm_provider("ollama"), OllamaProvider)

    async def test_resilient_retries_then_falls_back(self):
        from pawgrab.ai.providers import ResilientProvider

        class _Failing:
            calls = 0

            async def extract(self, *a, **k):
                _Failing.calls += 1
                raise RuntimeError("primary down")

        class _Fallback:
            async def extract(self, *a, **k):
                return {"ok": True}

        rp = ResilientProvider(_Failing(), _Fallback(), max_retries=2)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await rp.extract("c", "p")
        assert result == {"ok": True}
        assert _Failing.calls == 3  # 1 try + 2 retries before fallback


class TestAnthropicProvider:
    def _make_provider(self):
        with patch("pawgrab.ai.providers.settings") as mock_settings:
            mock_settings.anthropic_api_key = "test_key"
            mock_settings.anthropic_model = "claude-3"
            return AnthropicProvider(api_key="test_key", model="claude-3")

    @pytest.mark.asyncio
    async def test_extract_success(self):
        provider = self._make_provider()
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=MagicMock(content=[MagicMock(text='{"title": "Test Page"}')]))
        provider._client = mock_client

        result = await provider.extract("content text", "extract title")
        assert result == {"title": "Test Page"}

    @pytest.mark.asyncio
    async def test_invalid_json_returns_raw(self):
        provider = self._make_provider()
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=MagicMock(content=[MagicMock(text="not valid json")]))
        provider._client = mock_client

        result = await provider.extract("content", "prompt")
        assert "raw_response" in result

    @pytest.mark.asyncio
    async def test_api_error_raises(self):
        provider = self._make_provider()
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=RuntimeError("API error"))
        provider._client = mock_client

        with pytest.raises(RuntimeError, match="Anthropic API error"):
            await provider.extract("content", "prompt")


class TestOllamaProvider:
    def _make_provider(self):
        with patch("pawgrab.ai.providers.settings") as mock_settings:
            mock_settings.ollama_base_url = "http://localhost:11434"
            mock_settings.ollama_model = "llama3"
            return OllamaProvider(base_url="http://localhost:11434", model="llama3")

    @pytest.mark.asyncio
    async def test_extract_success(self):
        provider = self._make_provider()
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = AsyncMock(return_value=MagicMock(json=lambda: {"message": {"content": '{"extracted": "data"}'}}))

        with patch("curl_cffi.requests.AsyncSession", return_value=mock_session):
            result = await provider.extract("content", "extract data")

        assert result == {"extracted": "data"}

    @pytest.mark.asyncio
    async def test_api_error_raises(self):
        provider = self._make_provider()
        with patch("curl_cffi.requests.AsyncSession", side_effect=Exception("connection refused")):
            with pytest.raises(RuntimeError, match="Ollama API error"):
                await provider.extract("content", "prompt")
