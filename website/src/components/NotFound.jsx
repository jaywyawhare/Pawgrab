import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: 'calc(100vh - var(--navbar-height) - 100px)',
      padding: '2rem',
      textAlign: 'center',
      marginTop: 'var(--navbar-height)',
    }}>
      <h1 style={{
        fontFamily: 'var(--font-display)',
        fontSize: 'clamp(3rem, 8vw, 5rem)',
        fontWeight: 700,
        letterSpacing: '-0.03em',
        marginBottom: '0.5rem',
      }}>
        404
      </h1>
      <p style={{
        fontSize: '1.1rem',
        color: 'var(--text-2)',
        marginBottom: '2rem',
        maxWidth: '400px',
      }}>
        The page you're looking for doesn't exist or has been moved.
      </p>
      <Link
        to="/"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '0.5rem',
          padding: '0.7rem 1.5rem',
          borderRadius: 'var(--radius)',
          fontSize: '0.925rem',
          fontWeight: 600,
          background: 'var(--accent)',
          color: 'var(--bg)',
          textDecoration: 'none',
          transition: 'all 0.2s',
        }}
      >
        Go Home
      </Link>
    </div>
  )
}
