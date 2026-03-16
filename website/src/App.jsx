import { lazy, Suspense } from 'react'
import { Routes, Route } from 'react-router-dom'
import Navbar from './components/Navbar'
import Footer from './components/Footer'
import ErrorBoundary from './components/ErrorBoundary'

const Hero = lazy(() => import('./components/Hero'))
const FeatureTabs = lazy(() => import('./components/FeatureTabs'))
const Features = lazy(() => import('./components/Features'))
const Comparison = lazy(() => import('./components/Comparison'))
const CTA = lazy(() => import('./components/CTA'))
const DocsPage = lazy(() => import('./components/DocsPage'))
const NotFound = lazy(() => import('./components/NotFound'))

function Divider() {
  return <div className="divider" />
}

function Loading() {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      minHeight: 'calc(100vh - var(--navbar-height))',
      marginTop: 'var(--navbar-height)',
    }}>
      <div className="docs__loading-spinner" />
    </div>
  )
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
    <ErrorBoundary>
      <Navbar />
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/docs" element={<DocsPage />} />
          <Route path="/docs/:slug" element={<DocsPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
      <Footer />
    </ErrorBoundary>
  )
}
