# Skill: Crawl → content index

Crawl a site once; every page is written through to the content index. Later
queries are answered from the index (ranked, no live fetch).

## Steps

1. Start a crawl.
   ```bash
   curl -X POST $PAWGRAB/crawl \
     -H 'Content-Type: application/json' \
     -d '{"url": "https://docs.example.com", "max_pages": 100}'
   ```
   Every crawled page is indexed automatically (write-through).

2. Search the index — no network, ranked by relevance.
   ```bash
   curl -X POST $PAWGRAB/index/search \
     -H 'Content-Type: application/json' \
     -d '{"query": "authentication api key", "k": 5}'
   ```

3. Or let `/search` prefer the index for already-seen URLs:
   ```bash
   curl -X POST $PAWGRAB/search \
     -d '{"query": "example docs auth", "prefer_index": true}'
   ```
