import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import { ResendVerification } from '../components/ResendVerification'

/** Reads `token` from `#/verify-email?token=...` and removes it from the address bar at once (it is single use). */
export function takeTokenFromHash(): string {
  const [path, query = ''] = window.location.hash.split('?')
  const token = new URLSearchParams(query).get('token') ?? ''
  try {
    window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}${path}`)
  } catch {
    /* the token stays visible only in this tab */
  }
  return token
}

type State = { s: 'working' } | { s: 'ok' } | { s: 'bad'; message: string }

/** The page behind the e-mailed link: one POST, then success (sign-in link) or an error with a resend option. */
export function VerifyEmailPage() {
  const [token] = useState(takeTokenFromHash)
  const [state, setState] = useState<State>({ s: 'working' })
  const [email, setEmail] = useState('')
  const started = useRef(false)
  useEffect(() => {
    if (started.current) return
    started.current = true
    if (!token) {
      setState({ s: 'bad', message: 'This link has no confirmation code.' })
      return
    }
    api.verifyEmail(token)
      .then(() => setState({ s: 'ok' }))
      .catch((err: unknown) =>
        setState({
          s: 'bad',
          message: err instanceof ApiError && err.status === 429
            ? 'Too many attempts. Wait a few minutes and try again.'
            : 'This link is not valid any more. It may have been used already or have expired.',
        }),
      )
  }, [token])

  return (
    <div className="auth-page">
      <div className="card auth-card" data-testid="verify-email">
        <h2>Confirm your e-mail</h2>
        {state.s === 'working' && <p role="status">Confirming…</p>}
        {state.s === 'ok' && (
          <>
            <div role="status" data-variant="success" data-testid="verify-ok">Your e-mail address is confirmed.</div>
            <p><a href="#/" data-testid="verify-signin">Sign in</a></p>
          </>
        )}
        {state.s === 'bad' && (
          <>
            <div role="alert" data-variant="danger" data-testid="verify-bad">{state.message}</div>
            <label>
              Your e-mail address
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" />
            </label>
            {email.includes('@') ? <ResendVerification email={email} /> : <small className="muted">Enter your address to get a new link.</small>}
            <p className="muted small-text"><a href="#/">Back to sign in</a></p>
          </>
        )}
      </div>
    </div>
  )
}
