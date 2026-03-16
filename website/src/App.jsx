import { lazy, Suspense } from 'react'
import { Routes, Route } from 'react-router-dom'
import Navbar from './components/Navbar'
import Footer from './components/Footer'

const Hero = lazy(() => import('./components/Hero'))
const FeatureTabs = lazy(() => import('./components/FeatureTabs'))
const Features = lazy(() => import('./components/Features'))
const Comparison = lazy(() => import('./components/Comparison'))
const CTA = lazy(() => import('./components/CTA'))
const DocsPage = lazy(() => import('./components/DocsPage'))

function Divider() {
  return <div className="divider" />
}

function Landing() {
  return (
    <>
      <Hero />
      <Divider />
      <FeatureTabs />
      <Divider />
      <Features />
      <Divider />
      <Comparison />
      <Divider />
      <CTA />
    </>
  )
}

export default function App() {
  return (
    <>
      <Navbar />
      <Suspense fallback={null}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/docs" element={<DocsPage />} />
          <Route path="/docs/:slug" element={<DocsPage />} />
        </Routes>
      </Suspense>
      <Footer />
    </>
  )
}
