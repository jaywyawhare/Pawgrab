# Extraction Guide

The `/v1/extract` endpoint extracts structured data from web pages using AI (OpenAI) or deterministic strategies (CSS selectors, XPath, regex).

## LLM Extraction

Extract structured data using natural language prompts:

```bash
curl -X POST http://localhost:8000/v1/extract \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://example.com/products",
    "prompt": "Extract all products with name, price, and rating",
    "strategy": "llm"
  }'
```

### With JSON Schema

Enforce a strict output structure:

```json
{
  "url": "https://example.com/products",
  "prompt": "Extract all products",
  "strategy": "llm",
  "json_schema": {
    "type": "array",
    "items": {
      "type": "object",
      "properties": {
        "name": {"type": "string"},
        "price": {"type": "number"},
        "rating": {"type": "number"},
        "in_stock": {"type": "boolean"}
      },
      "required": ["name", "price"]
    }
  }
}
```

### Auto Schema

Let the LLM infer the schema automatically:

```json
{
  "url": "https://example.com/products",
  "prompt": "Extract product data",
  "auto_schema": true
}
```

### Chunking Strategies

For large pages, content is chunked before sending to the LLM:

| Strategy | Description |
|----------|-------------|
| `fixed` | Fixed-length chunks at sentence boundaries |
| `sliding` | Overlapping sliding window |
| `semantic` | Splits at paragraph and heading boundaries |

```json
{
  "url": "https://example.com/long-page",
  "prompt": "Extract key facts",
  "chunk_strategy": "semantic",
  "chunk_size": 4000,
  "chunk_overlap": 200
}
```

> **Note:** LLM extraction requires `PAWGRAB_OPENAI_API_KEY` to be set. Default model is `gpt-4o-mini`.

## CSS Selector Extraction

Deterministic extraction using CSS selectors — no LLM costs:

```json
{
  "url": "https://example.com/products",
  "strategy": "css",
  "selectors": {
    "title": "h1.product-title",
    "price": ".price-tag",
    "description": ".product-desc",
    "images": "img.product-image::attr(src)"
  }
}
```

## XPath Extraction

More powerful path-based extraction:

```json
{
  "url": "https://example.com/products",
  "strategy": "xpath",
  "xpath_queries": {
    "title": "//h1[@class='product-title']/text()",
    "prices": "//span[contains(@class, 'price')]/text()",
    "links": "//a[@class='product-link']/@href"
  }
}
```

## Regex Extraction

Pattern-based extraction:

```json
{
  "url": "https://example.com/page",
  "strategy": "regex",
  "patterns": {
    "emails": "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}",
    "phones": "\\+?\\d{1,3}[-.\\s]?\\(?\\d{3}\\)?[-.\\s]?\\d{3}[-.\\s]?\\d{4}",
    "prices": "\\$\\d+\\.\\d{2}"
  }
}
```

## Response Format

All extraction strategies return:

```json
{
  "success": true,
  "url": "https://example.com/products",
  "data": {
    "name": "Widget Pro",
    "price": 29.99,
    "rating": 4.8
  },
  "auto_schema": null,
  "error": null
}
```

## Choosing a Strategy

| Strategy | Best For | Cost | Speed |
|----------|----------|------|-------|
| `llm` | Unstructured data, complex extraction | Per-token API cost | Slower |
| `css` | Well-structured HTML, known selectors | Free | Fast |
| `xpath` | Complex DOM traversal | Free | Fast |
| `regex` | Pattern-based data (emails, phones) | Free | Fastest |
