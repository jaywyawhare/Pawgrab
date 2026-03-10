# Architecture

## Scrape Pipeline

`scrape_service.py` runs the full pipeline. Both `/v1/scrape` and the crawl worker use it.

1. robots.txt check (1h cache, 5min on failure)
2. Per-domain rate limit
3. Fetch with curl_cffi — random Safari/Chrome/Edge TLS fingerprint
4. If challenged → retry with different browser family
5. If JS needed (auto-detected or `wait_for_js=true`) → Playwright with stealth
6. Readability extraction
7. Optional pre/post filters: tag exclusion, CSS scoping, word count, pruning, BM25
8. Convert to requested formats
9. Optional captures: screenshot, PDF, network, console, MHTML, media, SSL, diff

## Fetcher Escalation

```
curl_cffi (Safari TLS) → challenge? → different family → still blocked? → Playwright
```

Challenge detection covers Cloudflare, reCAPTCHA, hCaptcha, Turnstile, AWS WAF, Akamai, Imperva, DataDome, PerimeterX, Sucuri.

Playwright stealth spoofs WebGL, canvas, audio, navigator, plugins, and WebRTC. Browser pool reuses contexts.

## Crawl

API creates a job in Redis and enqueues to ARQ. The worker:

1. Picks seed URL, initializes strategy (BFS/DFS/BestFirst)
2. Fetches page via the scrape pipeline
3. Extracts links, filters through `FilterChain` (domain, path, content type, dedup)
4. Adds new URLs to strategy queue
5. Checkpoints to Redis every 10 pages (crash recovery)
6. Publishes SSE events via Redis pub/sub
7. Fires webhook on completion

Max 5 concurrent jobs, 600s timeout each.

## Extract

LLM path: fetch → clean → markdown → chunk (if large) → OpenAI → merge chunk results.

Non-LLM: fetch → parse → CSS/XPath/Regex extractor.

Chunking strategies: fixed-length (sentence boundaries), sliding window (overlapping), semantic (paragraph/heading boundaries).

## Proxy Pool

Configured via env vars or the `/v1/proxy` API at runtime. Rotation policies: round-robin, random, least-used. Health checks run at configurable intervals. Proxies are soft-evicted after N failures with backoff cooldown. Per-proxy metrics track success rate, EMA speed, and failure counts.

## Dependencies

- **fastapi, uvicorn** — HTTP server
- **pydantic-settings** — config
- **curl_cffi** — TLS impersonation
- **playwright, playwright-stealth** — browser rendering
- **readabilipy** — content extraction
- **html2text** — HTML → Markdown
- **beautifulsoup4, lxml** — HTML parsing
- **openai** — LLM calls
- **arq, redis** — job queue
- **protego** — robots.txt
- **aiolimiter** — rate limiting
- **typer** — CLI
- **structlog** — logging
- **duckduckgo-search** — web search
- **pymupdf** — PDF text
