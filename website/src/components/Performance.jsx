import { useEffect, useRef } from 'react'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'

gsap.registerPlugin(ScrollTrigger)

const numbers = [
  { value: '6', label: 'Output Formats' },
  { value: '12+', label: 'API Endpoints' },
  { value: '80+', label: 'Config Options' },
  { value: '10+', label: 'Anti-Bot Bypasses' },
  { value: '3', label: 'Crawl Strategies' },
]

export default function Performance() {
  const ref = useRef(null)

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const ctx = gsap.context(() => {
      gsap.fromTo(ref.current.children,
        { y: 20, opacity: 0 },
        { y: 0, opacity: 1, duration: 0.5, stagger: 0.08, ease: 'power2.out',
          scrollTrigger: { trigger: ref.current, start: 'top 80%' } }
      )
    })
    return () => ctx.revert()
  }, [])

  return (
    <div id="performance" ref={ref} className="numbers">
      {numbers.map((n, i) => (
        <div className="numbers__item" key={i} style={{ opacity: 0 }}>
          <div className="numbers__value">{n.value}</div>
          <div className="numbers__label">{n.label}</div>
        </div>
      ))}
    </div>
  )
}
