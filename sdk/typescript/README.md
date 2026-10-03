# pawgrab-sdk (TypeScript)

Official TypeScript client for the Pawgrab web scraping API. Zero dependencies.

## Install

```bash
npm install pawgrab-sdk
```

## Usage

```typescript
import { PawgrabClient } from "pawgrab-sdk";

const client = new PawgrabClient("http://localhost:8000", process.env.PAWGRAB_API_KEY);

// Scrape — clean markdown by default
const page = await client.scrape("https://example.com");
console.log(page.markdown);

// Token-cheap LLM enrichment (one fetch, one LLM call)
const enriched = await client.scrape("https://example.com/article", {
  summary: true,
  question: "What is the main takeaway?",
  highlights: true,
});
console.log(enriched.summary, enriched.answer, enriched.highlights);

// Parse raw HTML without fetching
const parsed = await client.parse("<html><body><h1>Hello</h1></body></html>");

// Search with domain scoping
const serp = await client.search("python web scraping", {
  num_results: 5,
  exclude_domains: ["pinterest.com"],
});

// Structured extraction (requires PAWGRAB_OPENAI_API_KEY on the server)
const { data } = await client.extract("https://example.com", {
  prompt: "Extract the main heading",
});

// Crawl with polling
const job = await client.crawlAndWait("https://example.com", { max_pages: 10 });
console.log(job.results?.length);
```

API key is read from `PAWGRAB_API_KEY` when not passed to the constructor.
