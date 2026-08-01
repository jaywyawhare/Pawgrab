from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from pawgrab.cli.main import app

runner = CliRunner()


class TestScrapeCommand:
    def test_success(self):
        mock_result = MagicMock(html="<html><body><p>Hello world</p></body></html>", url="https://example.com")
        mock_cleaned = MagicMock(content_html="<p>Hello world</p>")

        with (
            patch("pawgrab.engine.fetcher.fetch_page", new_callable=AsyncMock, return_value=mock_result),
            patch("pawgrab.engine.cleaner.extract_content", return_value=mock_cleaned),
            patch("pawgrab.dependencies.get_browser_pool", new_callable=AsyncMock, return_value=None),
            patch("pawgrab.dependencies.shutdown_browser_pool", new_callable=AsyncMock),
        ):
            result = runner.invoke(app, ["scrape", "https://example.com"])

        assert result.exit_code == 0

    def test_format_flag(self):
        mock_result = MagicMock(html="<html><body><p>Content</p></body></html>", url="https://example.com")
        mock_cleaned = MagicMock(content_html="<p>Content</p>")

        with (
            patch("pawgrab.engine.fetcher.fetch_page", new_callable=AsyncMock, return_value=mock_result),
            patch("pawgrab.engine.cleaner.extract_content", return_value=mock_cleaned),
            patch("pawgrab.dependencies.get_browser_pool", new_callable=AsyncMock, return_value=None),
            patch("pawgrab.dependencies.shutdown_browser_pool", new_callable=AsyncMock),
        ):
            result = runner.invoke(app, ["scrape", "https://example.com", "--format", "text"])

        assert result.exit_code == 0

    def test_fetch_error_exits_1(self):
        with (
            patch("pawgrab.engine.fetcher.fetch_page", new_callable=AsyncMock, side_effect=Exception("Connection refused")),
            patch("pawgrab.dependencies.get_browser_pool", new_callable=AsyncMock, return_value=None),
            patch("pawgrab.dependencies.shutdown_browser_pool", new_callable=AsyncMock),
        ):
            result = runner.invoke(app, ["scrape", "https://example.com"])

        assert result.exit_code == 1


class TestExtractCommand:
    def test_success(self):
        with patch("pawgrab.ai.extractor.extract_from_url", new_callable=AsyncMock, return_value={"title": "Test"}):
            result = runner.invoke(app, ["extract", "https://example.com", "--prompt", "extract title"])

        assert result.exit_code == 0
        assert "title" in result.output

    def test_missing_prompt_fails(self):
        assert runner.invoke(app, ["extract", "https://example.com"]).exit_code != 0

    def test_error_exits_1(self):
        with patch("pawgrab.ai.extractor.extract_from_url", new_callable=AsyncMock, side_effect=Exception("LLM failed")):
            result = runner.invoke(app, ["extract", "https://example.com", "--prompt", "test"])

        assert result.exit_code == 1


class TestServeCommand:
    def test_calls_uvicorn_with_port(self):
        from pawgrab.config import settings

        with patch.object(settings, "allow_unauthenticated", True), patch("uvicorn.run") as mock_run:
            runner.invoke(app, ["serve", "--port", "9000"])

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert 9000 in call_args.args or call_args.kwargs.get("port") == 9000

    def test_default_host(self):
        from pawgrab.config import settings

        with patch.object(settings, "allow_unauthenticated", True), patch("uvicorn.run") as mock_run:
            runner.invoke(app, ["serve"])

        call_args = mock_run.call_args
        assert "0.0.0.0" in call_args.args or call_args.kwargs.get("host") == "0.0.0.0"

    def test_refuses_public_bind_without_auth(self):
        """Fail closed: no api_key + public interface + no opt-in => exit 1, no serve."""
        from pawgrab.config import settings

        with (
            patch.object(settings, "api_key", ""),
            patch.object(settings, "allow_unauthenticated", False),
            patch("uvicorn.run") as mock_run,
        ):
            result = runner.invoke(app, ["serve"])
        assert result.exit_code == 1
        mock_run.assert_not_called()

    def test_allows_loopback_without_auth(self):
        """Binding localhost without a key is allowed (dev)."""
        from pawgrab.config import settings

        with (
            patch.object(settings, "api_key", ""),
            patch.object(settings, "allow_unauthenticated", False),
            patch("uvicorn.run") as mock_run,
        ):
            runner.invoke(app, ["serve", "--host", "127.0.0.1"])
        mock_run.assert_called_once()


class TestHelpOutput:
    def test_main_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "scrape" in result.output
        assert "extract" in result.output
        assert "serve" in result.output

    def test_scrape_help(self):
        result = runner.invoke(app, ["scrape", "--help"])
        assert result.exit_code == 0
        assert "URL" in result.output

    def test_extract_help(self):
        result = runner.invoke(app, ["extract", "--help"])
        assert result.exit_code == 0
        assert "prompt" in result.output.lower()
