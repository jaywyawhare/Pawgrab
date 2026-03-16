import { useState, useEffect, useRef, memo } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'

gsap.registerPlugin(ScrollTrigger)

const codeTheme = {
  ...oneDark,
  'pre[class*="language-"]': {
    ...oneDark['pre[class*="language-"]'],
    background: 'transparent',
  },
  'code[class*="language-"]': {
    ...oneDark['code[class*="language-"]'],
    background: 'transparent',
  },
}

const tabs = [
  {
    id: 'scrape',
    label: 'Scrape',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
        <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
      </svg>
    ),
    description: 'Extract clean content from any URL. Get Markdown, HTML, text, JSON, CSV, or XML with a single request.',
    python: `import requests

resp = requests.post("http://localhost:8000/v1/scrape", json={
    "url": "https://news.ycombinator.com",
    "formats": ["markdown", "html"],
    "wait_for_js": True,
    "excluded_tags": ["nav", "footer"]
})

data = resp.json()
print(data["markdown"])`,
    curl: `curl -X POST http://localhost:8000/v1/scrape \\
  -H "Content-Type: application/json" \\
  -d '{
    "url": "https://news.ycombinator.com",
    "formats": ["markdown", "html"],
    "wait_for_js": true,
    "excluded_tags": ["nav", "footer"]
  }'`,
    response: `{
  "success": true,
  "url": "https://news.ycombinator.com",
  "metadata": {
    "title": "Hacker News",
    "status_code": 200,
    "word_count": 1842,
    "fetch_method": "browser"
  },
  "markdown": "# Hacker News\\n\\n1. Show HN: ...",
  "html": "<article>...</article>"
}`,
    status: '200 OK',
    time: '1.2s',
  },
  {
    id: 'crawl',
    label: 'Crawl',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="10" />
        <path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
      </svg>
    ),
    description: 'Async site crawling with BFS, DFS, or BestFirst strategies. Stream results via SSE in real-time.',
    python: `import requests

resp = requests.post("http://localhost:8000/v1/crawl", json={
    "url": "https://docs.example.com",
    "max_depth": 3,
    "max_pages": 100,
    "strategy": "bfs",
    "formats": ["markdown"],
    "include_path_patterns": ["/docs/*"]
})

job = resp.json()
print(f"Job ID: {job['job_id']}")
# Poll: GET /v1/crawl/{job_id}
# Stream: GET /v1/crawl/{job_id}/stream`,
    curl: `curl -X POST http://localhost:8000/v1/crawl \\
  -H "Content-Type: application/json" \\
  -H "Idempotency-Key: my-crawl-001" \\
  -d '{
    "url": "https://docs.example.com",
    "max_depth": 3,
    "max_pages": 100,
    "strategy": "bfs",
    "formats": ["markdown"],
    "include_path_patterns": ["/docs/*"]
  }'`,
    response: `{
  "success": true,
  "job_id": "crawl_a1b2c3d4",
  "status": "running",
  "poll_url": "/v1/crawl/crawl_a1b2c3d4",
  "stream_url": "/v1/crawl/crawl_a1b2c3d4/stream"
}`,
    status: '202 Accepted',
    time: 'async',
  },
  {
    id: 'extract',
    label: 'Extract',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
        <polyline points="7.5 4.21 12 6.81 16.5 4.21" />
        <polyline points="7.5 19.79 7.5 14.6 3 12" />
        <polyline points="21 12 16.5 14.6 16.5 19.79" />
        <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
        <line x1="12" y1="22.08" x2="12" y2="12" />
      </svg>
    ),
    description: 'Extract structured data with LLM (OpenAI), CSS selectors, XPath, or regex. Schema enforcement included.',
    python: `import requests

resp = requests.post("http://localhost:8000/v1/extract", json={
    "url": "https://example.com/products",
    "strategy": "llm",
    "prompt": "Extract all products with name, price, rating",
    "json_schema": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "price": {"type": "number"},
                "rating": {"type": "number"}
            }
        }
    }
})

products = resp.json()["data"]`,
    curl: `curl -X POST http://localhost:8000/v1/extract \\
  -H "Content-Type: application/json" \\
  -d '{
    "url": "https://example.com/products",
    "strategy": "llm",
    "prompt": "Extract all products with name, price, rating",
    "json_schema": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "name": {"type": "string"},
          "price": {"type": "number"},
          "rating": {"type": "number"}
        }
      }
    }
  }'`,
    response: `{
  "success": true,
  "data": [
    {"name": "Widget Pro", "price": 29.99, "rating": 4.8},
    {"name": "Gadget X", "price": 49.99, "rating": 4.5},
    {"name": "Tool Plus", "price": 19.99, "rating": 4.9}
  ],
  "tokens_used": 1250,
  "model": "gpt-4o-mini"
}`,
    status: '200 OK',
    time: '2.1s',
  },
  {
    id: 'search',
    label: 'Search',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
      </svg>
    ),
    description: 'Search the web and scrape each result in parallel. DuckDuckGo, SerpAPI, or Google Custom Search.',
    python: `import requests

resp = requests.post("http://localhost:8000/v1/search", json={
    "query": "best python web frameworks 2025",
    "num_results": 5,
    "formats": ["markdown"],
    "provider": "duckduckgo"
})

for result in resp.json()["results"]:
    print(result["title"])
    print(result["markdown"][:200])`,
    curl: `curl -X POST http://localhost:8000/v1/search \\
  -H "Content-Type: application/json" \\
  -d '{
    "query": "best python web frameworks 2025",
    "num_results": 5,
    "formats": ["markdown"],
    "provider": "duckduckgo"
  }'`,
    response: `{
  "success": true,
  "query": "best python web frameworks 2025",
  "results": [
    {
      "url": "https://blog.example.com/frameworks",
      "title": "Top Python Web Frameworks",
      "markdown": "# Top Python Web Frameworks..."
    }
  ],
  "total": 5,
  "failed_urls": []
}`,
    status: '200 OK',
    time: '3.4s',
  },
  {
    id: 'map',
    label: 'Map',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6" />
        <line x1="8" y1="2" x2="8" y2="18" /><line x1="16" y1="6" x2="16" y2="22" />
      </svg>
    ),
    description: 'Discover all URLs from a site via sitemap parsing or homepage link crawling.',
    python: `import requests

resp = requests.post("http://localhost:8000/v1/map", json={
    "url": "https://example.com",
    "include_subdomains": False,
    "limit": 500
})

urls = resp.json()["urls"]
print(f"Found {len(urls)} URLs")`,
    curl: `curl -X POST http://localhost:8000/v1/map \\
  -H "Content-Type: application/json" \\
  -d '{
    "url": "https://example.com",
    "include_subdomains": false,
    "limit": 500
  }'`,
    response: `{
  "success": true,
  "url": "https://example.com",
  "source": "sitemap",
  "urls": [
    "https://example.com/",
    "https://example.com/about",
    "https://example.com/docs",
    "https://example.com/blog/post-1"
  ],
  "total": 247
}`,
    status: '200 OK',
    time: '0.8s',
  },
]

const CopyBtn = memo(function CopyBtn({ text }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      className="ft-copy"
      onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500) }}
      aria-label="Copy code"
    >
      {copied ? (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true"><polyline points="20 6 9 17 4 12" /></svg>
      ) : (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" /></svg>
      )}
    </button>
  )
})

export default function FeatureTabs() {
  const [active, setActive] = useState('scrape')
  const [lang, setLang] = useState('python')
  const sectionRef = useRef(null)
  const tab = tabs.find((t) => t.id === active)

  useEffect(() => {
    const ctx = gsap.context(() => {
      gsap.from('.feature-tabs', {
        scrollTrigger: { trigger: '.feature-tabs', start: 'top 85%' },
        opacity: 0,
        y: 40,
        duration: 0.7,
      })
    }, sectionRef)
    return () => ctx.revert()
  }, [])

  const codeText = lang === 'python' ? tab.python : tab.curl

  return (
    <section className="feature-tabs" ref={sectionRef}>
      <div className="feature-tabs__inner">
        <div className="section-header">
          <span className="section-label">Endpoints</span>
          <h2 className="section-title">One API, endless possibilities</h2>
          <p className="section-desc">
            Scrape pages, crawl sites, extract structured data, search the web,
            and map sitemaps, all from a unified REST API.
          </p>
        </div>

        <div className="feature-tabs__tabs">
          {tabs.map((t) => (
            <button
              key={t.id}
              className={`feature-tabs__tab ${active === t.id ? 'feature-tabs__tab--active' : ''}`}
              onClick={() => setActive(t.id)}
            >
              <span className="feature-tabs__tab-icon">{t.icon}</span>
              {t.label}
            </button>
          ))}
        </div>

        <AnimatePresence mode="wait">
          <motion.div
            key={active}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2 }}
            className="feature-tabs__content"
          >
            <p className="feature-tabs__desc">{tab.description}</p>

            <div className="feature-tabs__panels">
              {/* Request panel */}
              <div className="feature-tabs__panel">
                <div className="feature-tabs__panel-header">
                  <span className="feature-tabs__panel-title">Request</span>
                  <div className="feature-tabs__lang-switcher">
                    <button className={`feature-tabs__lang ${lang === 'python' ? 'feature-tabs__lang--active' : ''}`} onClick={() => setLang('python')}>Python</button>
                    <button className={`feature-tabs__lang ${lang === 'curl' ? 'feature-tabs__lang--active' : ''}`} onClick={() => setLang('curl')}>cURL</button>
                  </div>
                  <CopyBtn text={codeText} />
                </div>
                <SyntaxHighlighter
                  language={lang === 'python' ? 'python' : 'bash'}
                  style={codeTheme}
                  customStyle={{
                    margin: 0,
                    padding: '1rem 1.15rem',
                    background: 'transparent',
                    fontSize: '0.78rem',
                    lineHeight: 1.7,
                    overflow: 'auto',
                    maxHeight: 360,
                  }}
                  codeTagProps={{ style: { fontFamily: 'var(--font-mono)' } }}
                >
                  {codeText}
                </SyntaxHighlighter>
              </div>

              {/* Response panel */}
              <div className="feature-tabs__panel feature-tabs__panel--response">
                <div className="feature-tabs__panel-header">
                  <span className="feature-tabs__panel-title">Response</span>
                  <div className="feature-tabs__meta">
                    <span className="feature-tabs__status">{tab.status}</span>
                    <span className="feature-tabs__time">{tab.time}</span>
                  </div>
                  <CopyBtn text={tab.response} />
                </div>
                <SyntaxHighlighter
                  language="json"
                  style={codeTheme}
                  customStyle={{
                    margin: 0,
                    padding: '1rem 1.15rem',
                    background: 'transparent',
                    fontSize: '0.78rem',
                    lineHeight: 1.7,
                    overflow: 'auto',
                    maxHeight: 360,
                  }}
                  codeTagProps={{ style: { fontFamily: 'var(--font-mono)' } }}
                >
                  {tab.response}
                </SyntaxHighlighter>
              </div>
            </div>
          </motion.div>
        </AnimatePresence>
      </div>
    </section>
  )
}
