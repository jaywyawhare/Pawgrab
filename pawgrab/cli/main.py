"""Pawgrab CLI — scrape, extract, and serve from the command line."""

from __future__ import annotations

import asyncio

import orjson
import typer
from rich.console import Console

app = typer.Typer(name="pawgrab", help="Web scraping API")
console = Console()


@app.command()
def scrape(
    url: str = typer.Argument(..., help="URL to scrape"),
    format: str = typer.Option("markdown", "--format", "-f", help="Output format: markdown, html, text, json"),
    js: bool = typer.Option(False, "--js", help="Force JavaScript rendering"),
):
    """Scrape a single URL and print the result."""
    from pawgrab.engine.cleaner import extract_content
    from pawgrab.engine.converter import convert
    from pawgrab.engine.fetcher import fetch_page
    from pawgrab.models.common import OutputFormat

    async def _run():
        """Fetch, clean, and convert the URL, tearing the browser pool down after."""
        from pawgrab.dependencies import get_browser_pool, shutdown_browser_pool

        pool = await get_browser_pool()
        try:
            result = await fetch_page(
                url,
                wait_for_js=js if js else None,
                browser_pool=pool,
            )
            cleaned = extract_content(result.html, url=result.url)
            fmt = OutputFormat(format)
            return convert(cleaned.content_html, fmt)
        finally:
            await shutdown_browser_pool()

    try:
        output = asyncio.run(_run())
        console.print(output, markup=False)
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted[/dim]")
        raise typer.Exit(1) from None
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc


@app.command()
def extract(
    url: str = typer.Argument(..., help="URL to extract data from"),
    prompt: str = typer.Option(..., "--prompt", "-p", help="Extraction prompt"),
):
    """Extract structured data from a URL using AI."""
    from pawgrab.ai.extractor import extract_from_url

    async def _run():
        """Run the AI extraction for the given URL and prompt."""
        return await extract_from_url(url, prompt=prompt)

    try:
        data = asyncio.run(_run())
        console.print_json(orjson.dumps(data, option=orjson.OPT_INDENT_2).decode())
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted[/dim]")
        raise typer.Exit(1) from None
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc


@app.command()
def doctor(
    json_output: bool = typer.Option(False, "--json", help="Emit the raw diagnostics as JSON"),
):
    """Report which capabilities are usable with the current configuration."""
    from pawgrab.engine.diagnostics import run_diagnostics

    report = run_diagnostics()
    if json_output:
        console.print_json(orjson.dumps(report).decode())
        return
    from rich.table import Table

    colors = {"ok": "green", "warn": "yellow", "off": "dim"}
    table = Table(title=f"Pawgrab capabilities — {report['status']}")
    table.add_column("Capability")
    table.add_column("Status")
    table.add_column("Detail")
    for name, cap in report["capabilities"].items():
        status = cap["status"]
        table.add_row(name, f"[{colors.get(status, 'white')}]{status}[/]", cap["message"])
    console.print(table)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h"),
    port: int = typer.Option(8000, "--port", "-p"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload"),
):
    """Start the Pawgrab API server."""
    import uvicorn

    from pawgrab.config import settings

    loopback = host in ("127.0.0.1", "localhost", "::1")
    if not settings.api_key and not settings.allow_unauthenticated and not loopback:
        console.print(
            "[red]Refusing to start:[/red] no PAWGRAB_API_KEY set and binding a "
            f"public interface ({host}). Set PAWGRAB_API_KEY, or "
            "PAWGRAB_ALLOW_UNAUTHENTICATED=true to run open, or bind 127.0.0.1."
        )
        raise typer.Exit(code=1)
    if not settings.api_key:
        console.print("[yellow]Warning:[/yellow] running without authentication (no PAWGRAB_API_KEY).")
    uvicorn.run("pawgrab.main:app", host=host, port=port, reload=reload)


@app.command()
def mcp(
    api_url: str = typer.Option(None, "--api-url", help="Running Pawgrab API to call (default: PAWGRAB_MCP_API_URL)"),
):
    """Run the MCP server (stdio) exposing Pawgrab tools to AI agents.

    Talks to a running Pawgrab API over HTTP — start one with `pawgrab serve`.
    Requires the mcp extra: pip install "pawgrab[mcp]".
    """
    from pawgrab.config import settings

    if api_url:
        settings.mcp_api_url = api_url
    try:
        from pawgrab.mcp.server import run
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    run()


if __name__ == "__main__":
    app()
