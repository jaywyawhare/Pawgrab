# Live interact

Keep a scraped page alive and drive it with code actions or an AI prompt, then read
its content or a live screenshot.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/scrape/live` | Open a URL and keep the page alive; returns a `scrape_id` |
| `POST` | `/scrape/{scrape_id}/interact` | Drive the live page (code actions or AI prompt) |
| `GET`  | `/scrape/{scrape_id}/live.png` | Live screenshot (the `live_view_url` bytes) |
| `DELETE` | `/scrape/{scrape_id}` | Close the session and free the page |

## Start a session

```bash
curl -X POST http://localhost:8000/scrape/live \
  -d '{"url": "https://example.com/login", "formats": ["markdown"]}'
# -> { "scrape_id": "ab12…", "live_view_url": "/scrape/ab12…/live.png", ... }
```

## Interact — code mode

```bash
curl -X POST http://localhost:8000/scrape/ab12…/interact \
  -d '{"mode": "code", "actions": [
        {"type": "type", "selector": "#user", "text": "demo"},
        {"type": "click", "selector": "button[type=submit]"},
        {"type": "wait", "amount": 1000}
      ], "formats": ["markdown"]}'
```

## Interact — AI mode

```bash
curl -X POST http://localhost:8000/scrape/ab12…/interact \
  -d '{"mode": "ai", "prompt": "accept the cookie banner and open the pricing tab"}'
```

The LLM turns the prompt into page actions, runs them, and returns the refreshed
content plus the `planned_actions`.

## Limitation

Live pages live **in the worker process** that created them (a browser page can't be
serialized). In a multi-worker deployment, route follow-up requests to the same
process (sticky sessions) or run a single browser worker. Idle sessions are reaped
after `PAWGRAB_LIVE_SESSION_TTL` seconds (default 300); capacity is
`PAWGRAB_LIVE_SESSION_MAX` (default 20).
