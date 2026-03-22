# Pawgrab Python SDK

Official Python client for the [Pawgrab](https://github.com/your-repo/pawgrab) web scraping API.

## Installation

```bash
pip install pawgrab-sdk
```

## Quick Start

```python
from pawgrab_sdk import PawgrabClient, ScrapeOptions

# Async usage
async with PawgrabClient("http://localhost:8000", api_key="your-key") as client:
    # Simple scrape
    result = await client.scrape("https://example.com")
    print(result.markdown)

    # With options
    result = await client.scrape("https://example.com", ScrapeOptions(
        formats=["markdown", "text"],
        llm_ready=True,
        cache_ttl=300,
    ))

    # Extract structured data
    from pawgrab_sdk import ExtractOptions
    data = await client.extract("https://example.com", ExtractOptions(
        strategy="llm",
        prompt="Extract all product names and prices",
    ))

    # Crawl a site
    from pawgrab_sdk import CrawlOptions
    job = await client.crawl("https://example.com", CrawlOptions(max_pages=50))
    status = await client.wait_for_crawl(job.job_id)

# Sync usage
client = PawgrabClient("http://localhost:8000")
result = client.scrape_sync("https://example.com")
```
