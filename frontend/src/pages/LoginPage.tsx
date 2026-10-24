import { useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { useAuth } from '../components/AuthProvider'

/** Hints shown under the password box while signing up; the server enforces the real policy. */
const PASSWORD_HINT = 'At least 12 characters. A few random words work well.'

export function LoginPage() {
  const { signIn, signUp } = useAuth()
  const [mode, setMode] = useState<'signin' | 'signup'>('signin')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'signin') await signIn(email, password)
      else await signUp(email, password, name)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(
          err.status === 429
            ? 'Too many attempts. Wait a few minutes and try again.'
            : err.message,
        )
      } else {
        setError("Can't reach the server. Check that the backend is running.")
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="card auth-card">
        <div className="branding auth-brand">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="3" y="3" width="7" height="7" rx="1" />
            <rect x="14" y="3" width="7" height="7" rx="1" />
            <rect x="14" y="14" width="7" height="7" rx="1" />
            <rect x="3" y="14" width="7" height="7" rx="1" />
          </svg>
          <span>Backend Builder</span>
        </div>
        <h2>{mode === 'signin' ? 'Sign in' : 'Create your account'}</h2>

        <form onSubmit={submit}>
          {error && (
            <div role="alert" data-variant="danger">
              {error}
            </div>
          )}
          {mode === 'signup' && (
            <label>
              Name
              <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
            </label>
          )}
          <label>
            Email
            <input
              type="email"
              required
              autoFocus
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <label>
            Password
            <input
              type="password"
              required
              minLength={mode === 'signup' ? 12 : undefined}
              autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {mode === 'signup' && <small className="muted">{PASSWORD_HINT}</small>}
          </label>
          <button type="submit" disabled={busy}>
            {busy ? 'Please wait…' : mode === 'signin' ? 'Sign in' : 'Create account'}
          </button>
        </form>

        <p className="muted small-text auth-switch">
          {mode === 'signin' ? 'New here?' : 'Already have an account?'}{' '}
          <a
            href="#/"
            onClick={(e) => {
              e.preventDefault()
              setError(null)
              setMode(mode === 'signin' ? 'signup' : 'signin')
            }}
          >
            {mode === 'signin' ? 'Create an account' : 'Sign in'}
          </a>
        </p>
      </div>
    </div>
  )
}
