import { Link } from 'react-router-dom'

export default function Footer() {
  return (
    <footer className="footer">
      <div>
        <div className="footer__brand">Pawgrab</div>
        <div className="footer__sub">Professional-grade web scraping API.</div>
      </div>
      <div className="footer__links">
        <a href="https://github.com/jaywyawhare/Pawgrab" target="_blank" rel="noopener noreferrer">GitHub</a>
        <a href="https://pypi.org/project/pawgrab/" target="_blank" rel="noopener noreferrer">PyPI</a>
        <a href="#features">Features</a>
        <Link to="/docs">Docs</Link>
      </div>
    </footer>
  )
}
