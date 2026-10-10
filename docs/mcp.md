# MCP Server

Pawgrab ships a [Model Context Protocol](https://modelcontextprotocol.io) server
so AI agents and MCP-capable clients can use Pawgrab's scraping capabilities as
tools.

The MCP server is a thin layer over a **running Pawgrab API** — it forwards each
tool call to the HTTP API over the network. Start an API first, then run the MCP
server pointing at it.

## Install

```bash
pip install "pawgrab[mcp]"
```

## Run

```bash
# 1. Start the API (in one shell)
pawgrab serve

# 2. Run the MCP server over stdio (in another)
pawgrab mcp
```

By default the server talks to `http://localhost:8000`. Override it with the
`--api-url` flag or the `PAWGRAB_MCP_API_URL` environment variable:

```bash
pawgrab mcp --api-url https://pawgrab.internal
```

If the API requires authentication (`PAWGRAB_API_KEY` is set), the MCP server
sends it as a `Bearer` token automatically.

## Client configuration

Register Pawgrab with an MCP client (example shape):

```json
{
  "mcpServers": {
    "pawgrab": {
      "command": "pawgrab",
      "args": ["mcp"],
      "env": {
        "PAWGRAB_MCP_API_URL": "http://localhost:8000",
        "PAWGRAB_API_KEY": "your-key-if-any"
      }
    }
  }
}
```

## Tools

| Tool | Description | API endpoint |
|------|-------------|--------------|
| `scrape` | Scrape a URL to markdown/html/text/json | `POST /v1/scrape` |
| `parse` | Clean raw HTML without fetching | `POST /v1/parse` |
| `extract` | Structured extraction (LLM/CSS/XPath/regex, with `adaptive`) | `POST /v1/extract` |
| `search` | Web search + scrape each result | `POST /v1/search` |
| `map_site` | Discover URLs via sitemap or shallow crawl | `POST /v1/map` |
| `crawl` | Start an async crawl job (returns a job id) | `POST /v1/crawl` |
| `crawl_status` | Poll a crawl job's status and results | `GET /v1/crawl/{job_id}` |

Each tool returns the API's JSON envelope. Transport and HTTP errors are mapped to
a structured `{"error": ..., "code": ...}` object so the agent always receives a
usable result.
