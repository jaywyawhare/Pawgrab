import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'

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

const DOC_SECTIONS = [
  {
    title: 'Getting Started',
    items: [
      { slug: 'index', label: 'Overview' },
      { slug: 'quickstart', label: 'Quick Start' },
    ],
  },
  {
    title: 'Guides',
    items: [
      { slug: 'scraping', label: 'Scraping' },
      { slug: 'crawling', label: 'Crawling' },
      { slug: 'extraction', label: 'Extraction' },
    ],
  },
  {
    title: 'API Reference',
    items: [
      { slug: 'api', label: 'API Endpoints' },
      { slug: 'cli', label: 'CLI' },
    ],
  },
  {
    title: 'Configuration',
    items: [
      { slug: 'configuration', label: 'Configuration' },
    ],
  },
  {
    title: 'Advanced',
    items: [
      { slug: 'architecture', label: 'Architecture' },
      { slug: 'deployment', label: 'Deployment' },
    ],
  },
]

const ALL_DOCS = DOC_SECTIONS.flatMap((s) => s.items)

function generateId(text) {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .trim()
}

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = () => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <button className="docs-copy-btn" onClick={handleCopy} aria-label="Copy code">
      {copied ? (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
          <polyline points="20 6 9 17 4 12" />
        </svg>
      ) : (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
          <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
        </svg>
      )}
    </button>
  )
}

export default function DocsPage() {
  const { slug } = useParams()
  const activeSlug = slug || 'index'
  const navigate = useNavigate()
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [toc, setToc] = useState([])
  const [activeHeading, setActiveHeading] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const contentRef = useRef(null)

  useEffect(() => {
    setLoading(true)
    setSidebarOpen(false)
    const base = import.meta.env.BASE_URL || '/'
    fetch(`${base}docs/${activeSlug}.md`)
      .then((res) => {
        if (!res.ok) throw new Error('Not found')
        return res.text()
      })
      .then((text) => {
        // Strip frontmatter
        const stripped = text.replace(/^---[\s\S]*?---\n*/, '')
        setContent(stripped)

        // Generate TOC
        const headings = []
        const regex = /^#{2,3}\s+(.+)$/gm
        let match
        while ((match = regex.exec(stripped)) !== null) {
          const level = match[0].startsWith('###') ? 3 : 2
          headings.push({ text: match[1], id: generateId(match[1]), level })
        }
        setToc(headings)
        setLoading(false)

        // Scroll to top
        if (contentRef.current) {
          contentRef.current.scrollTo(0, 0)
        }
        window.scrollTo(0, 0)
      })
      .catch(() => {
        setContent('# Page Not Found\n\nThe requested documentation page could not be found.')
        setToc([])
        setLoading(false)
      })
  }, [activeSlug])

  // Intersection observer for TOC highlighting
  useEffect(() => {
    if (!contentRef.current || toc.length === 0) return
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveHeading(entry.target.id)
          }
        }
      },
      { rootMargin: '-80px 0px -70% 0px' }
    )
    const headingEls = contentRef.current.querySelectorAll('h2[id], h3[id]')
    headingEls.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [toc, content])

  const currentIdx = ALL_DOCS.findIndex((d) => d.slug === activeSlug)
  const prev = currentIdx > 0 ? ALL_DOCS[currentIdx - 1] : null
  const next = currentIdx < ALL_DOCS.length - 1 ? ALL_DOCS[currentIdx + 1] : null

  // Find section for breadcrumb
  const currentSection = DOC_SECTIONS.find((s) => s.items.some((i) => i.slug === activeSlug))
  const currentDoc = ALL_DOCS.find((d) => d.slug === activeSlug)

  const handleLinkClick = useCallback(
    (href) => {
      if (href.endsWith('.md')) {
        const docSlug = href.replace(/\.md$/, '').replace(/^\.\//, '')
        navigate(`/docs/${docSlug}`)
        return true
      }
      return false
    },
    [navigate]
  )

  return (
    <div className="docs">
      <button
        className="docs__sidebar-toggle"
        onClick={() => setSidebarOpen(!sidebarOpen)}
        aria-label="Toggle sidebar"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <line x1="3" y1="6" x2="21" y2="6" />
          <line x1="3" y1="12" x2="21" y2="12" />
          <line x1="3" y1="18" x2="21" y2="18" />
        </svg>
      </button>

      <aside className={`docs__sidebar ${sidebarOpen ? 'docs__sidebar--open' : ''}`}>
        <div className="docs__sidebar-inner">
          {DOC_SECTIONS.map((section) => (
            <div className="docs__section" key={section.title}>
              <h4 className="docs__section-title">
                {section.title}
              </h4>
              {section.items.map((item) => (
                <Link
                  key={item.slug}
                  to={`/docs/${item.slug}`}
                  className={`docs__nav-link ${activeSlug === item.slug ? 'docs__nav-link--active' : ''}`}
                >
                  {item.label}
                </Link>
              ))}
            </div>
          ))}
        </div>
      </aside>

      <main className="docs__content" ref={contentRef}>
        {/* Breadcrumb */}
        <div className="docs__breadcrumb">
          <Link to="/docs" className="docs__breadcrumb-link">Docs</Link>
          {currentSection && (
            <>
              <span className="docs__breadcrumb-sep">/</span>
              <span className="docs__breadcrumb-section">{currentSection.title}</span>
            </>
          )}
          {currentDoc && (
            <>
              <span className="docs__breadcrumb-sep">/</span>
              <span className="docs__breadcrumb-current">{currentDoc.label}</span>
            </>
          )}
        </div>

        {loading ? (
          <div className="docs__loading">
            <div className="docs__loading-spinner" />
          </div>
        ) : (
          <div className="docs__markdown">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeRaw]}
              components={{
                h2: ({ children }) => {
                  const id = generateId(String(children))
                  return <h2 id={id}>{children}</h2>
                },
                h3: ({ children }) => {
                  const id = generateId(String(children))
                  return <h3 id={id}>{children}</h3>
                },
                code: ({ inline, className, children, ...props }) => {
                  const match = /language-(\w+)/.exec(className || '')
                  const codeStr = String(children).replace(/\n$/, '')
                  if (!inline && match) {
                    return (
                      <div className="docs__code-block">
                        <div className="docs__code-header">
                          <span className="docs__code-lang">{match[1]}</span>
                          <CopyButton text={codeStr} />
                        </div>
                        <SyntaxHighlighter
                          style={codeTheme}
                          language={match[1]}
                          PreTag="div"
                          customStyle={{
                            margin: 0,
                            borderRadius: '0 0 8px 8px',
                            background: 'var(--bg-code)',
                            fontSize: '0.875rem',
                          }}
                          {...props}
                        >
                          {codeStr}
                        </SyntaxHighlighter>
                      </div>
                    )
                  }
                  return <code className="docs__inline-code" {...props}>{children}</code>
                },
                a: ({ href, children, ...props }) => {
                  if (href && href.endsWith('.md')) {
                    const docSlug = href.replace(/\.md$/, '').replace(/^\.\//, '')
                    return <Link to={`/docs/${docSlug}`}>{children}</Link>
                  }
                  if (href && (href.startsWith('http://') || href.startsWith('https://'))) {
                    return <a href={href} target="_blank" rel="noopener noreferrer" {...props}>{children}</a>
                  }
                  return <a href={href} {...props}>{children}</a>
                },
                table: ({ children }) => (
                  <div className="docs__table-wrap">
                    <table>{children}</table>
                  </div>
                ),
                blockquote: ({ children }) => (
                  <blockquote className="docs__blockquote">{children}</blockquote>
                ),
              }}
            >
              {content}
            </ReactMarkdown>
          </div>
        )}

        {/* Prev / Next nav */}
        <div className="docs__nav-footer">
          {prev ? (
            <Link to={`/docs/${prev.slug}`} className="docs__nav-prev">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M19 12H5M12 19l-7-7 7-7" />
              </svg>
              <div>
                <span className="docs__nav-label">Previous</span>
                <span className="docs__nav-title">{prev.label}</span>
              </div>
            </Link>
          ) : <div />}
          {next ? (
            <Link to={`/docs/${next.slug}`} className="docs__nav-next">
              <div>
                <span className="docs__nav-label">Next</span>
                <span className="docs__nav-title">{next.label}</span>
              </div>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M5 12h14M12 5l7 7-7 7" />
              </svg>
            </Link>
          ) : <div />}
        </div>
      </main>

      {/* Table of Contents */}
      {toc.length > 0 && (
        <aside className="docs__toc">
          <h4 className="docs__toc-title">On this page</h4>
          {toc.map((heading) => (
            <a
              key={heading.id}
              href={`#${heading.id}`}
              className={`docs__toc-link ${heading.level === 3 ? 'docs__toc-link--sub' : ''} ${
                activeHeading === heading.id ? 'docs__toc-link--active' : ''
              }`}
            >
              {heading.text}
            </a>
          ))}
        </aside>
      )}
    </div>
  )
}
