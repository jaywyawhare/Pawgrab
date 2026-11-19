"""Model Context Protocol server for Pawgrab.

Exposes Pawgrab's scraping capabilities as MCP tools backed by a running
Pawgrab API over HTTP. The client functions live in ``client`` (no MCP
dependency); ``server`` wires them onto a FastMCP server.
"""

from pawgrab.mcp.client import (
    agent,
    crawl,
    crawl_status,
    index_search,
    map_site,
    parse,
    scrape,
    search,
)

__all__ = ["scrape", "parse", "agent", "index_search", "search", "map_site", "crawl", "crawl_status"]
