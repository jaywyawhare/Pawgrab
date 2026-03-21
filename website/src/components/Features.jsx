import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'

gsap.registerPlugin(ScrollTrigger)

const features = [
  {
    title: 'Anti-Bot Evasion',
    desc: 'TLS fingerprint impersonation with curl_cffi, stealth browser profiles, and automatic challenge detection for Cloudflare, reCAPTCHA, and more.',
    tags: ['TLS Fingerprint', 'Stealth', 'curl_cffi'],
    link: '/docs/scraping',
  },
  {
    title: '6 Output Formats',
    desc: 'Markdown, HTML, plain text, JSON, CSV, or XML. Readability-based content extraction ensures clean output with no boilerplate.',
    tags: ['Markdown', 'JSON', 'CSV'],
    link: '/docs/scraping',
  },
  {
    title: 'Smart JS Detection',
    desc: 'Starts with fast curl_cffi. Automatically escalates to headless Patchright only when JavaScript rendering is truly needed.',
    tags: ['Auto-Escalation', 'Patchright'],
    link: '/docs/architecture',
  },
  {
    title: 'Async Crawling',
    desc: 'BFS, DFS, and BestFirst strategies with depth/page limits. Redis-backed job queue with SSE streaming and crash recovery.',
    tags: ['BFS', 'DFS', 'Redis Queue'],
    link: '/docs/crawling',
  },
  {
    title: 'LLM Extraction',
    desc: 'Extract structured data using OpenAI with JSON schema enforcement. Or use CSS selectors, XPath, and regex for zero-cost extraction.',
    tags: ['OpenAI', 'CSS/XPath', 'Schema'],
    link: '/docs/extraction',
  },
  {
    title: 'Proxy Rotation',
    desc: 'Built-in proxy pool with round-robin, random, and least-used policies. Health checking, backoff, and runtime management via API.',
    tags: ['Round-Robin', 'Health Check'],
    link: '/docs/configuration',
  },
  {
    title: 'Rate Limiting',
    desc: 'Per-domain and API-level rate limiting with configurable RPM. Returns proper 429 + Retry-After headers.',
    tags: ['Per-Domain', '429 Headers'],
    link: '/docs/api',
  },
  {
    title: 'robots.txt Compliant',
    desc: 'Automatic robots.txt checking with 1-hour cache. Respects crawl rules by default. Override per-request when needed.',
    tags: ['Auto-Cache', 'Respectful'],
    link: '/docs/configuration',
  },
  {
    title: 'Docker Ready',
    desc: 'Full Docker Compose stack: API server, ARQ workers, and Redis. Health checks, memory limits, and auto-restart out of the box.',
    tags: ['Compose', 'ARQ Workers', 'Redis'],
    link: '/docs/deployment',
  },
]

export default function Features() {
  const ref = useRef(null)

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const el = ref.current
    if (!el) return

    const ctx = gsap.context(() => {
      gsap.fromTo('.section-header-feat',
        { y: 24, opacity: 0 },
        { y: 0, opacity: 1, duration: 0.6, ease: 'power2.out',
          scrollTrigger: { trigger: el, start: 'top 85%' } }
      )
      gsap.fromTo(el.querySelectorAll('.features__card'),
        { y: 30, opacity: 0 },
        { y: 0, opacity: 1, duration: 0.5, stagger: 0.04, ease: 'power2.out',
          scrollTrigger: { trigger: el, start: 'top 75%' } }
      )
    })
    return () => ctx.revert()
  }, [])

  return (
    <section className="features" id="features" ref={ref}>
      <div className="features__inner">
        <div className="section-header" style={{marginBottom: 48 }}>
          <div className="section-label">Capabilities</div>
          <h2 className="section-title">Everything you need to scrape the web</h2>
          <p className="section-desc">
            Battle-tested features for production web scraping, from anti-bot evasion to structured extraction.
          </p>
        </div>

        <div className="features__grid">
          {features.map((f, i) => (
            <Link to={f.link} className="features__card" key={i}>
              <h3 className="features__card-title">{f.title}</h3>
              <p className="features__card-desc">{f.desc}</p>
              <div className="features__card-tags">
                {f.tags.map((t, j) => <span key={j} className="features__card-tag">{t}</span>)}
              </div>
            </Link>
          ))}
        </div>
      </div>
    </section>
  )
}
