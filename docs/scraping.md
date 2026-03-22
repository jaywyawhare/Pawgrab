# Scraping Guide

The `/v1/scrape` endpoint is Pawgrab's core — extract clean content from any URL.

## Basic Scraping

```bash
curl -X POST http://localhost:8000/v1/scrape \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com"}'
```

By default, returns Markdown content with metadata.

## Output Formats

Request any combination of 6 formats:

```json
{
  "url": "https://example.com",
  "formats": ["markdown", "html", "text", "json", "csv", "xml"]
}
```

Only requested formats are populated in the response — others are `null`.

## JavaScript Rendering

Pawgrab uses a smart escalation strategy:

1. **Auto mode** (default) — Starts with fast `curl_cffi`, auto-detects if JS is needed
2. **Force browser** — Set `"wait_for_js": true`
3. **Skip browser** — Set `"wait_for_js": false`

```json
{
  "url": "https://spa-app.example.com",
  "wait_for_js": true,
  "timeout": 30000
}
```

## Content Filtering

Control what gets extracted:

```json
{
  "url": "https://example.com",
  "excluded_tags": ["nav", "footer", "aside", "header"],
  "excluded_selector": ".ads, .sidebar, .cookie-banner",
  "css_selector": "article.main-content",
  "word_count_threshold": 20,
  "citations": true
}
```

### BM25 Relevance Filtering

Extract only the most relevant sections:

```json
{
  "url": "https://docs.example.com/api",
  "content_filter": "bm25",
  "content_filter_query": "authentication",
  "fit_markdown_query": "how to authenticate",
  "fit_markdown_top_k": 5
}
```

## Rich Captures

Capture screenshots, PDFs, network logs, and more (requires browser):

```json
{
  "url": "https://example.com",
  "wait_for_js": true,
  "screenshot": true,
  "screenshot_fullpage": true,
  "pdf": true,
  "capture_network": true,
  "capture_console": true,
  "capture_mhtml": true,
  "extract_media": true,
  "capture_ssl": true
}
```

## Page Actions

Automate interactions before extraction:

```json
{
  "url": "https://example.com/login",
  "wait_for_js": true,
  "actions": [
    {"type": "WAIT_FOR", "selector": "#login-form"},
    {"type": "TYPE", "selector": "#email", "text": "user@example.com"},
    {"type": "TYPE", "selector": "#password", "text": "password"},
    {"type": "CLICK", "selector": "#submit-btn"},
    {"type": "WAIT", "amount": 2000},
    {"type": "SCREENSHOT"}
  ]
}
```

### Action Types

| Type | Parameters | Description |
|------|-----------|-------------|
| `CLICK` | `selector` | Click an element |
| `TYPE` | `selector`, `text` | Type text into an input |
| `SCROLL` | `direction`, `amount` | Scroll up/down by pixels |
| `WAIT` | `amount` | Wait for milliseconds |
| `WAIT_FOR` | `selector` | Wait for element to appear |
| `SCREENSHOT` | — | Take a mid-action screenshot |
| `EXECUTE_JS` | `text` | Execute JavaScript code |

## Change Tracking

Monitor content changes over time:

```json
{
  "url": "https://example.com/pricing",
  "monitor": true,
  "monitor_ttl": 86400
}
```

The response will include a `diff` field showing what changed since the last scrape.

## Custom Headers & Cookies

```json
{
  "url": "https://example.com",
  "headers": {"Authorization": "Bearer token123"},
  "cookies": {"session": "abc123"}
}
```

## Anti-Bot Evasion

Pawgrab automatically handles anti-bot challenges:

1. **TLS Fingerprinting** — curl_cffi impersonates real browser TLS signatures (Safari, Chrome, Edge)
2. **Challenge Detection** — Detects Cloudflare, reCAPTCHA, hCaptcha, Turnstile, AWS WAF, Akamai, Imperva, DataDome, PerimeterX, Sucuri
3. **Automatic Retry** — On challenge, retries with different browser family
4. **Stealth Browser** — Patchright with spoofed WebGL, canvas, audio, navigator, plugins, and WebRTC
5. **Proxy Rotation** — Route through rotating proxies to avoid IP bans

## Response Format

```json
{
  "success": true,
  "url": "https://example.com",
  "warning": null,
  "metadata": {
    "title": "Example",
    "description": "An example page",
    "language": "en",
    "url": "https://example.com",
    "status_code": 200,
    "word_count": 450
  },
  "markdown": "# Example\n\nContent here...",
  "html": null,
  "text": null,
  "screenshot_base64": null,
  "pdf_base64": null,
  "diff": null
}
```
