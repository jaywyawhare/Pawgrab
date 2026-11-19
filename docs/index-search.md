# Content index

A write-through cache of every page Pawgrab scrapes ("Alexandria-lite"). Repeat and
search queries can be answered from the index, ranked by relevance, without a live
fetch.

## How it fills

Every successful `/scrape`, each `/crawl` page, and every `/agent` fetch is
written through to the index. Unchanged pages are skipped via a content hash (the
same hashing used by change-tracking), so re-scraping a static page is cheap.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/index/search` | Search cached pages, ranked lexically (BM25) |
| `GET`  | `/index/stats` | Index size and backing store |
| `DELETE` | `/index/{domain}` | Evict every cached page for a domain |

```bash
curl -X POST http://localhost:8000/index/search \
  -d '{"query": "authentication api key", "k": 5, "include_content": false}'
```

## Prefer the index from search

`/search` accepts `prefer_index: true` — result URLs already in the index are
served from cache instead of being re-fetched, which is faster and lighter.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `PAWGRAB_INDEX_ENABLED` | `true` | Master switch |
| `PAWGRAB_INDEX_TTL` | `604800` | Entry TTL in seconds (0 = no expiry) |
| `PAWGRAB_INDEX_MAX_ENTRIES` | `100000` | Cap on cached entries |
| `PAWGRAB_INDEX_STORE` | `redis` | `redis` or `sqlite` |
| `PAWGRAB_EMBEDDINGS_ENABLED` | `false` | Use embeddings for ranking when a provider is configured |

Backed by Redis; if Redis is unavailable the index degrades to a process-local store
so it never blocks a scrape.
