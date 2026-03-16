import { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'

gsap.registerPlugin(ScrollTrigger)

export default function CTA() {
  const ref = useRef(null)

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const ctx = gsap.context(() => {
      gsap.fromTo(ref.current.children,
        { y: 20, opacity: 0 },
        { y: 0, opacity: 1, duration: 0.5, stagger: 0.08, ease: 'power2.out',
          scrollTrigger: { trigger: ref.current, start: 'top 85%' } }
      )
    })
    return () => ctx.revert()
  }, [])

  return (
    <div ref={ref} className="cta">
      <h2 className="cta__title" style={{ opacity: 0 }}>Start scraping.</h2>
      <p className="cta__desc" style={{ opacity: 0 }}>
        Install, start, and make your first API call. No configuration required.
      </p>
      <div className="cta__actions" style={{ opacity: 0 }}>
        <Link to="/docs/quickstart" className="cta__btn cta__btn--primary">
          Get Started
        </Link>
        <a
          href="https://github.com/jaywyawhare/Pawgrab"
          target="_blank"
          rel="noopener noreferrer"
          className="cta__btn"
        >
          View on GitHub
        </a>
      </div>
    </div>
  )
}
