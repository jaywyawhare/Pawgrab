"""MCP server exposing Pawgrab tools over stdio.

Requires the optional ``mcp`` dependency: ``pip install "pawgrab[mcp]"``.
Tools call a running Pawgrab API; start one with ``pawgrab serve`` first.
"""

from __future__ import annotations

from typing import Any

from pawgrab.mcp import client


def _server_class():
    """Return the MCP server class across SDK versions (2.x MCPServer, 1.x FastMCP)."""
    try:
        from mcp.server.mcpserver import MCPServer

        return MCPServer
    except ImportError:
        pass
    try:
        from mcp.server.fastmcp import FastMCP

        return FastMCP
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError('MCP support requires the "mcp" extra: pip install "pawgrab[mcp]"') from exc


def build_server():
    """Construct the MCP server with all Pawgrab tools registered."""
    server = _server_class()("pawgrab")

    @server.tool()
    async def scrape(
        url: str,
        formats: list[str] | None = None,
        wait_for_js: bool | None = None,
        timeout: int = 30000,
    ) -> dict[str, Any]:
        """Scrape a single URL and return clean markdown, html, text, or json."""
        return await client.scrape(url, formats=formats, wait_for_js=wait_for_js, timeout=timeout)

    @server.tool()
    async def parse(
        html: str,
        formats: list[str] | None = None,
        css_selector: str | None = None,
    ) -> dict[str, Any]:
        """Convert raw HTML to clean output formats without fetching it."""
        return await client.parse(html, formats=formats, css_selector=css_selector)

    @server.tool()
    async def extract(
        url: str,
        prompt: str | None = None,
        strategy: str = "llm",
        selectors: dict[str, Any] | None = None,
        adaptive: bool = False,
    ) -> dict[str, Any]:
        """Extract structured data from a URL via LLM, CSS, XPath, or regex."""
        return await client.extract(url, prompt=prompt, strategy=strategy, selectors=selectors, adaptive=adaptive)

    @server.tool()
    async def search(
        query: str,
        num_results: int = 5,
        exclude_domains: list[str] | None = None,
    ) -> dict[str, Any]:
        """Search the web and scrape each result."""
        return await client.search(query, num_results=num_results, exclude_domains=exclude_domains)

    @server.tool()
    async def map_site(url: str, limit: int = 100) -> dict[str, Any]:
        """Discover URLs for a site via its sitemap or a shallow crawl."""
        return await client.map_site(url, limit=limit)

    @server.tool()
    async def crawl(url: str, max_pages: int = 10, max_depth: int = 2) -> dict[str, Any]:
        """Start an async crawl job; returns a job id to poll with crawl_status."""
        return await client.crawl(url, max_pages=max_pages, max_depth=max_depth)

    @server.tool()
    async def crawl_status(job_id: str) -> dict[str, Any]:
        """Get the status and results of a crawl job."""
        return await client.crawl_status(job_id)

    return server


def run() -> None:
    """Run the MCP server over stdio."""
    build_server().run()
