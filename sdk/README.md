# Pawgrab SDKs

All clients are generated from one source of truth — the FastAPI OpenAPI schema —
so every endpoint (`scrape`, `crawl`, `agent`, `map`, `search`, `batch`, `interact`,
`index`, …) appears in every language automatically.

## Languages

| Language | Package | Install |
|----------|---------|---------|
| Python | `pawgrab` | `pip install pawgrab` |
| TypeScript / Node | `pawgrab` | `npm install pawgrab` |
| Go | `github.com/jaywyawhare/Pawgrab/sdk/go` | `go get …/sdk/go` |
| Rust | `pawgrab` | `cargo add pawgrab` |
| Java | `dev.pawgrab:pawgrab` | Maven / Gradle |
| Ruby | `pawgrab` | `gem install pawgrab` |
| PHP | `pawgrab/pawgrab` | `composer require pawgrab/pawgrab` |
| .NET | `Pawgrab` | `dotnet add package Pawgrab` |
| Elixir | `pawgrab` | `{:pawgrab, "~> 0.1"}` |

## Regenerating

```bash
# dump the schema only
python -m pawgrab.openapi > sdk/openapi.json

# regenerate every SDK (needs openapi-generator-cli on PATH)
./sdk/generate.sh
```

Each language dir keeps two parts:

- `generated/` — the mechanical client (never hand-edited; overwritten by the script).
- a thin idiomatic wrapper beside it that adds crawl-polling helpers and matches the
  Python SDK's ergonomics.

CI (`.github/workflows/sdks.yml`) regenerates on any API change and smoke-tests each
SDK against a live container, so a drifting client fails the build.
