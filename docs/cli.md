# CLI Reference

Pawgrab includes a command-line interface for quick scraping and server management.

## Installation

```bash
pip install pawgrab
patchright install chromium
```

## Commands

### scrape

Scrape a single URL and print the result:

```bash
# Default: Markdown output
pawgrab scrape https://example.com

# Plain text output
pawgrab scrape https://example.com --format text

# HTML output
pawgrab scrape https://example.com --format html

# Force JavaScript rendering
pawgrab scrape https://example.com --js

# Skip JavaScript rendering
pawgrab scrape https://example.com --no-js
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--format` | `markdown` | Output format: `markdown`, `html`, `text` |
| `--js` / `--no-js` | auto | Force or skip browser rendering |

### extract

Extract structured data using AI:

```bash
pawgrab extract https://example.com --prompt "Extract the main heading and summary"
```

### Options

| Flag | Required | Description |
|------|----------|-------------|
| `--prompt` | Yes | Natural language extraction prompt |

> **Note:** Requires `PAWGRAB_OPENAI_API_KEY` environment variable.

### serve

Start the API server:

```bash
# Default: 0.0.0.0:8000
pawgrab serve

# Custom host and port
pawgrab serve --host 127.0.0.1 --port 9000

# Development mode with auto-reload
pawgrab serve --reload
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `0.0.0.0` | Server bind address |
| `--port` | `8000` | Server port |
| `--reload` | off | Watch for code changes |

## Environment Variables

The CLI respects all `PAWGRAB_*` environment variables. See the [Configuration](configuration.md) page for the full list.

You can set them in a `.env` file in your working directory:

```bash
cp .env.example .env
# Edit .env with your settings
```
