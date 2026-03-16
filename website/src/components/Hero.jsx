import { useEffect, useRef, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import gsap from 'gsap'
import { useWebGraph } from '../hooks/useWebGraph'

export default function Hero() {
  const canvasRef = useWebGraph()
  const inner = useRef(null)
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText('pip install pawgrab')
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }, [])

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const ctx = gsap.context(() => {
      const tl = gsap.timeline({ delay: 0.3, defaults: { ease: 'power3.out' } })
      tl.fromTo('.hero__badge', { y: 16, opacity: 0 }, { y: 0, opacity: 1, duration: 0.5 })
        .fromTo('.hero__title', { y: 24, opacity: 0 }, { y: 0, opacity: 1, duration: 0.6 }, '-=0.3')
        .fromTo('.hero__subtitle', { y: 20, opacity: 0 }, { y: 0, opacity: 1, duration: 0.5 }, '-=0.35')
        .fromTo('.hero__install', { y: 16, opacity: 0 }, { y: 0, opacity: 1, duration: 0.5 }, '-=0.3')
        .fromTo('.hero__actions', { y: 12, opacity: 0 }, { y: 0, opacity: 1, duration: 0.4 }, '-=0.25')
    }, inner)
    return () => ctx.revert()
  }, [])

  return (
    <section className="hero">
      <canvas ref={canvasRef} className="hero__canvas" />
      <div className="hero__fade" />

      <div ref={inner} className="hero__content">
        <div className="hero__badge" style={{ opacity: 0 }}>
          <span className="hero__badge-dot" />
          Open Source &middot; Production Ready
        </div>

        <h1 className="hero__title" style={{ opacity: 0 }}>
          Turn any URL into<br />
          <span className="hero__title-accent">clean, structured data</span>
        </h1>

        <p className="hero__subtitle" style={{ opacity: 0 }}>
          Professional-grade web scraping API with anti-bot evasion,
          multiple output formats, async crawling, and LLM-ready extraction.
        </p>

        <div className="hero__install" style={{ opacity: 0 }} onClick={handleCopy}>
          <code>
            <span className="hero__install-prompt">$</span> pip install pawgrab
          </code>
          <button className="hero__install-copy" aria-label="Copy">
            {copied ? (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            ) : (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
              </svg>
            )}
          </button>
        </div>

        <div className="hero__actions" style={{ opacity: 0 }}>
          <Link to="/docs" className="hero__btn hero__btn--primary">
            Get Started
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
              <path d="M5 12h14M12 5l7 7-7 7" />
            </svg>
          </Link>
          <a
            href="https://github.com/jaywyawhare/Pawgrab"
            target="_blank"
            rel="noopener noreferrer"
            className="hero__btn hero__btn--ghost"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/>
            </svg>
            View on GitHub
          </a>
        </div>
      </div>
    </section>
  )
}
