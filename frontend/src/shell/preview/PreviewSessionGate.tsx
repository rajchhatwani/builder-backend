import { useId, useState, type ReactNode } from 'react'
import { waitingMessage, type PreviewSession } from './previewSession'

/** Renders its children only when the preview session is ready; otherwise explains what is missing and offers the next step.
 *  The page owns the h1; the gate adds no headings. `prefix` namespaces the test ids (e.g. "ledger"). */
export function PreviewSessionGate({ session, prefix, children }: { session: PreviewSession; prefix: string; children: ReactNode }) {
  const emailId = useId(), passId = useId()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const s = session.status

  if (s === 'ready') return <>{children}</>

  async function run(fn: (e: string, p: string) => Promise<string | null>) {
    setBusy(true); setMsg(null)
    const m = await fn(email.trim(), password)
    setBusy(false)
    if (m) setMsg(m); else setPassword('')
  }

  if (s === 'no-origin') {
    return <p className="muted" data-testid={`${prefix}-no-origin`}>No preview API address is configured for this dashboard, so there is nothing to connect to yet. Set <code>VITE_PREVIEW_API_ORIGIN</code> or <code>VITE_API_BASE_URL</code>.</p>
  }
  if (s === 'loading' || s === 'starting') {
    return <p role="status" className="muted" data-testid="preview-session-wait">{waitingMessage(s, session.previewState)}</p>
  }
  if (s === 'no-preview') {
    return (
      <div className="stack" data-testid="preview-session-none">
        <p className="muted">This project has no running preview. Start one to see live data here. Connecting refreshes the preview access token, so a token you copied before stops working.</p>
        <div><button type="button" onClick={() => void session.start()} data-testid="preview-start">Start a preview</button></div>
      </div>
    )
  }
  if (s === 'error') {
    return (
      <div className="stack" data-testid="preview-session-error">
        <p role="alert" className="error-text">{session.error ?? 'The preview session could not be set up.'}</p>
        <div><button type="button" className="outline" onClick={() => void session.start()} data-testid="preview-retry">Start a new preview</button></div>
      </div>
    )
  }
  // needs-signin
  const wait = waitingMessage(s, session.previewState)
  return (
    <form className="stack" data-testid="preview-signin" onSubmit={(e) => { e.preventDefault(); void run(session.signIn) }}>
      <p className="muted">Sign in to the preview app with one of its own accounts (the roles you set up apply). Connecting refreshes the preview access token. Nothing is stored in your browser.</p>
      {wait && <p role="status" className="muted">{wait}</p>}
      <div className="hstack">
        <label htmlFor={emailId}>Preview app email</label>
        <input id={emailId} type="email" autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} data-testid="preview-email" />
        <label htmlFor={passId}>Preview app password</label>
        <input id={passId} type="password" autoComplete="off" value={password} onChange={(e) => setPassword(e.target.value)} data-testid="preview-password" />
      </div>
      <div className="hstack">
        <button type="submit" disabled={busy || !email.trim() || !password} data-testid="preview-signin-btn">Sign in</button>
        <button type="button" className="outline" disabled={busy || !email.trim() || password.length < 8} onClick={() => void run(session.register)} data-testid="preview-register">Create test account</button>
      </div>
      {msg && <p role="alert" className="error-text" data-testid="preview-signin-error">{msg}</p>}
    </form>
  )
}
