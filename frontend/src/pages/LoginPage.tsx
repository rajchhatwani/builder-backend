import { useCallback, useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import type { LoginDiscovery, MfaChallenge } from '../api/types'
import { useAuth } from '../components/AuthProvider'
import { MfaStep } from '../components/MfaStep'
import { ssoErrorText } from '../api/ssoErrors'

/** Hints shown under the password box while signing up; the server enforces the real policy. */
const PASSWORD_HINT = 'At least 12 characters. A few random words work well.'

function ssoErrorFromHash(): string | null {
  // Landed on #/sso/complete but there was no session to resume (cookie blocked or expired).
  if (window.location.hash.startsWith('#/sso/complete')) return "The SSO sign-in didn't finish. Try again."
  const query = window.location.hash.split('?')[1]
  const reason = query ? new URLSearchParams(query).get('sso_error') : null
  return reason ? ssoErrorText(reason) : null
}

function errorText(err: unknown): string {
  if (!(err instanceof ApiError)) return "Can't reach the server. Check that the backend is running."
  return err.status === 429 ? 'Too many attempts. Wait a few minutes and try again.' : err.message
}

type Step =
  | { kind: 'email' }
  | { kind: 'sso'; discovery: LoginDiscovery }
  | { kind: 'password' }
  | { kind: 'mfa'; challenge: MfaChallenge }

export function LoginPage() {
  const { signIn, signUp, completeSignIn } = useAuth()
  const [mode, setMode] = useState<'signin' | 'signup'>('signin')
  const [step, setStep] = useState<Step>({ kind: 'email' })
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(ssoErrorFromHash)
  const [busy, setBusy] = useState(false)

  const restart = useCallback((reason: string | null) => {
    setPassword('')
    setStep({ kind: 'password' })
    setError(reason)
  }, [])

  async function discover() {
    try {
      const found = await api.discoverLogin(email.trim())
      setStep(found.method === 'sso' && found.login_url ? { kind: 'sso', discovery: found } : { kind: 'password' })
    } catch (err) {
      // Discovery is a convenience: if it fails, the password form still works.
      if (err instanceof ApiError && err.status === 429) setError(errorText(err))
      setStep({ kind: 'password' })
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'signup') await signUp(email, password, name)
      else if (step.kind === 'email') await discover()
      else {
        const challenge = await signIn(email, password)
        if (challenge) setStep({ kind: 'mfa', challenge })
      }
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  function switchMode() {
    setError(null)
    setStep({ kind: 'email' })
    setMode(mode === 'signin' ? 'signup' : 'signin')
  }

  const brand = (
    <div className="branding auth-brand">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="3" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="14" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" />
      </svg>
      <span>Backend Builder</span>
    </div>
  )

  if (mode === 'signin' && step.kind === 'mfa') {
    return (
      <div className="auth-page">
        <div className="card auth-card">
          {brand}
          <MfaStep challenge={step.challenge} steps={api.loginMfa} onSignedIn={completeSignIn} onRestart={restart} />
        </div>
      </div>
    )
  }

  const askPassword = mode === 'signup' || step.kind === 'password'

  return (
    <div className="auth-page">
      <div className="card auth-card">
        {brand}
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
              autoFocus={step.kind === 'email' || mode === 'signup'}
              autoComplete="username"
              value={email}
              readOnly={mode === 'signin' && step.kind !== 'email'}
              onChange={(e) => setEmail(e.target.value)}
            />
            {mode === 'signin' && step.kind !== 'email' && (
              <small>
                <a
                  href="#/"
                  onClick={(e) => {
                    e.preventDefault()
                    setError(null)
                    setPassword('')
                    setStep({ kind: 'email' })
                  }}
                >
                  Use a different email
                </a>
              </small>
            )}
          </label>

          {step.kind === 'sso' && mode === 'signin' ? (
            <div className="stack">
              <p className="small-text">
                {step.discovery.organization_name ?? 'Your organization'} signs you in through its identity provider.
              </p>
              <button
                type="button"
                onClick={() => {
                  // A full navigation: the IdP round trip ends back here at #/sso/complete.
                  if (step.discovery.login_url) window.location.href = step.discovery.login_url
                }}
              >
                Continue with {step.discovery.organization_name ?? 'your organization'} SSO
              </button>
              <small className="muted">
                <a
                  href="#/"
                  onClick={(e) => {
                    e.preventDefault()
                    setStep({ kind: 'password' })
                  }}
                >
                  Sign in with a password instead
                </a>
              </small>
            </div>
          ) : (
            <>
              {askPassword && (
                <label>
                  Password
                  <input
                    type="password"
                    required
                    autoFocus={mode === 'signin'}
                    minLength={mode === 'signup' ? 12 : undefined}
                    autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                  {mode === 'signup' && <small className="muted">{PASSWORD_HINT}</small>}
                </label>
              )}
              <button type="submit" disabled={busy}>
                {busy ? 'Please wait…' : mode === 'signup' ? 'Create account' : askPassword ? 'Sign in' : 'Continue'}
              </button>
            </>
          )}
        </form>

        <p className="muted small-text auth-switch">
          {mode === 'signin' ? 'New here?' : 'Already have an account?'}{' '}
          <a
            href="#/"
            onClick={(e) => {
              e.preventDefault()
              switchMode()
            }}
          >
            {mode === 'signin' ? 'Create an account' : 'Sign in'}
          </a>
        </p>
      </div>
    </div>
  )
}
