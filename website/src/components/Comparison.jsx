import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { useEffect, useRef } from 'react'

gsap.registerPlugin(ScrollTrigger)

const numbers = [
  { value: '6', label: 'Output Formats' },
  { value: '12+', label: 'API Endpoints' },
  { value: '80+', label: 'Config Options' },
  { value: '10+', label: 'Anti-Bot Bypasses' },
  { value: '3', label: 'Crawl Strategies' },
]

const tools = [
  { name: 'Playwright*', single: 101, multi: 887, type: 'baseline' },
  { name: 'Pawgrab', single: 504, multi: 1646, type: 'highlight' },
  { name: 'requests + BS4', single: 1138, multi: 3497, type: 'normal' },
  { name: 'httpx + BS4', single: 1233, multi: 3129, type: 'normal' },
  { name: 'Scrapy', single: 1327, multi: 3238, type: 'normal' },
  { name: 'trafilatura', single: 1344, multi: 5221, type: 'normal' },
  { name: 'Crawl4AI', single: 2575, multi: 10586, type: 'normal' },
  { name: 'Selenium', single: 3534, multi: 8089, type: 'normal' },
]

const maxMs = Math.max(...tools.flatMap(t => [t.single, t.multi]))

function formatMs(ms) {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}

function ToolRow({ tool, index }) {
  const singlePct = (tool.single / maxMs) * 100
  const multiPct = (tool.multi / maxMs) * 100
  const hl = tool.type === 'highlight'

  return (
    <div className={`bench__row${hl ? ' bench__row--hl' : ''}`}>
      <span className={`bench__name${hl ? ' bench__name--hl' : ''}`}>
        {tool.name}
      </span>
      <div className="bench__pairs">
        <div className="bench__pair">
          <div className="bench__track">
            <div
              className="bench__fill bench__fill--single"
              style={{ '--bw': `${singlePct}%`, '--bd': `${index * 0.07}s` }}
            />
          </div>
          <span className={`bench__ms${hl ? ' bench__ms--hl' : ''}`}>{formatMs(tool.single)}</span>
        </div>
        <div className="bench__pair">
          <div className="bench__track">
            <div
              className="bench__fill bench__fill--multi"
              style={{ '--bw': `${multiPct}%`, '--bd': `${index * 0.07 + 0.04}s` }}
            />
          </div>
          <span className={`bench__ms${hl ? ' bench__ms--hl' : ''}`}>{formatMs(tool.multi)}</span>
        </div>
      </div>
    </div>
  )
}

export default function Comparison() {
  const ref = useRef(null)

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const ctx = gsap.context(() => {
      gsap.fromTo('.perf__numbers .numbers__item',
        { y: 20, opacity: 0 },
        { y: 0, opacity: 1, duration: 0.5, stagger: 0.06, ease: 'power2.out',
          scrollTrigger: { trigger: '.perf__numbers', start: 'top 80%' } }
      )
      gsap.from('.bench__card', {
        scrollTrigger: { trigger: '.bench__card', start: 'top 85%' },
        opacity: 0,
        y: 30,
        duration: 0.6,
      })
    }, ref)
    return () => ctx.revert()
  }, [])

  return (
    <section className="comparison" id="comparison" ref={ref}>
      <div className="comparison__inner">
        <div className="section-header">
          <span className="section-label">Performance</span>
          <h2 className="section-title">How Pawgrab stacks up</h2>
          <p className="section-desc">
            Key metrics and real benchmarks against popular scraping tools.
          </p>
        </div>

        <div className="perf__numbers">
          {numbers.map((n, i) => (
            <div className="numbers__item" key={i}>
              <div className="numbers__value">{n.value}</div>
              <div className="numbers__label">{n.label}</div>
            </div>
          ))}
        </div>

        <div className="bench__card">
          <div className="bench__header">
            <div>
              <h3 className="bench__title">Scraping Speed Comparison</h3>
              <span className="bench__subtitle">
                End-to-end latency &middot; content extraction + anti-bot evasion
              </span>
            </div>
            <div className="bench__legend">
              <span className="bench__legend-item">
                <span className="bench__legend-dot bench__legend-dot--single" />
                Single page
              </span>
              <span className="bench__legend-item">
                <span className="bench__legend-dot bench__legend-dot--multi" />
                10 pages
              </span>
            </div>
          </div>
          <div className="bench__body">
            {tools.map((tool, i) => (
              <ToolRow key={tool.name} tool={tool} index={i} />
            ))}
          </div>
          <div className="bench__footer">
            <span className="bench__note">
              * Playwright reuses a warm browser page with no extraction or anti-bot evasion.
            </span>
          </div>
        </div>
      </div>
    </section>
  )
}
