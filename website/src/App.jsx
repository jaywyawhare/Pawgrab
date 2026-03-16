import { Routes, Route } from 'react-router-dom'
import Navbar from './components/Navbar'
import Hero from './components/Hero'
import FeatureTabs from './components/FeatureTabs'
import Features from './components/Features'
import Comparison from './components/Comparison'
import Footer from './components/Footer'
import DocsPage from './components/DocsPage'

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
    </>
  )
}

export default function App() {
  return (
    <>
      <Navbar />
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/docs" element={<DocsPage />} />
        <Route path="/docs/:slug" element={<DocsPage />} />
      </Routes>
      <Footer />
    </>
  )
}
