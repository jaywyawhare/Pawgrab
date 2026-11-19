# Agent

`POST /agent` runs a bounded research agent that navigates pages to satisfy a
natural-language goal and (optionally) a JSON schema. It supersedes the old
single-shot `/extract`.

## Request

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `prompt` | string | required | The goal, e.g. "find the pricing tiers and monthly cost" |
| `urls` | array | `[]` | Seed URLs; if empty the agent searches the web to find them |
| `schema` | object | null | JSON schema the final `data` must satisfy |
| `effort` | enum | `medium` | `low` (3 steps) · `medium` (8) · `high` (20) |
| `max_steps` | int | null | Overrides the effort budget |
| `allowed_domains` | array | `[]` | If set, the agent may only navigate to these domains |

## How it works

Each step the model picks one tool — `search`, `fetch`, or `finish` — and the loop
executes it, accumulating page content until the goal is met or the budget runs out.
Every fetched page is also written through to the [content index](index-search.md).

## Response

```json
{
  "success": true,
  "data": { "tiers": [{ "name": "Pro", "monthly_usd": 20 }] },
  "sources": ["https://example.com/pricing"],
  "steps": [
    { "action": "fetch", "url": "https://example.com/pricing", "reason": "read pricing", "tokens": 420 },
    { "action": "finish", "reason": "schema satisfied" }
  ],
  "total_tokens": 420
}
```

## Example

```bash
curl -X POST http://localhost:8000/agent \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "What is the latest version and its release date?", "urls": ["https://example.com/releases"], "effort": "low"}'
```

Requires an LLM provider (`PAWGRAB_OPENAI_API_KEY`, or another configured provider).
Budgets are tunable via `PAWGRAB_AGENT_STEPS_LOW/MEDIUM/HIGH` and
`PAWGRAB_AGENT_TOKEN_CAP`.
