import { Component } from 'react'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  render() {
    if (this.state.hasError) {
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
            fontSize: '1.5rem',
            fontWeight: 700,
            marginBottom: '0.75rem',
          }}>
            Something went wrong
          </h1>
          <p style={{
            fontSize: '1rem',
            color: 'var(--text-2)',
            marginBottom: '2rem',
          }}>
            An unexpected error occurred.
          </p>
          <button
            onClick={() => {
              this.setState({ hasError: false })
              window.location.reload()
            }}
            style={{
              padding: '0.7rem 1.5rem',
              borderRadius: 'var(--radius)',
              fontSize: '0.925rem',
              fontWeight: 600,
              background: 'var(--accent)',
              color: 'var(--bg)',
              border: 'none',
              cursor: 'pointer',
            }}
          >
            Reload Page
          </button>
        </div>
      )
    }

    return this.props.children
  }
}
