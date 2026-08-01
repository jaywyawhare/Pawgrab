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
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h"),
    port: int = typer.Option(8000, "--port", "-p"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload"),
):
    """Start the Pawgrab API server."""
    import uvicorn

    from pawgrab.config import settings

    # Fail closed: refuse to expose an unauthenticated server on a non-loopback
    # interface unless the operator explicitly opted in.
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


if __name__ == "__main__":
    app()
