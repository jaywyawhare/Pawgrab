# CLI

```bash
pip install pawgrab
playwright install chromium
```

## scrape

```bash
pawgrab scrape https://example.com
pawgrab scrape https://example.com --format text
pawgrab scrape https://example.com --js
```

`--format` - `markdown` (default), `html`, `text`. `--js` / `--no-js` - force or skip browser rendering (auto by default).

## extract

```bash
pawgrab extract https://example.com --prompt "Extract the main heading and summary"
```

`--prompt` is required. Needs `PAWGRAB_OPENAI_API_KEY`.

## serve

```bash
pawgrab serve
pawgrab serve --host 127.0.0.3 --port 9000 --reload
```

`--host` (default `0.0.0.0`), `--port` (default `8000`), `--reload` (watch for code changes).
