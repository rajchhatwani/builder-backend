import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'

/** The server allows one mail per 60 s per account; the button waits the same time. */
export const RESEND_COOLDOWN_SECONDS = 60

/** "Send the link again" with a visible countdown. `email` may be a function for callers that do not know it yet. */
export function ResendVerification({ email, startCooling = false }: { email: string | (() => Promise<string>); startCooling?: boolean }) {
  const [left, setLeft] = useState(startCooling ? RESEND_COOLDOWN_SECONDS : 0)
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (left <= 0) return
    const t = setTimeout(() => setLeft((n) => n - 1), 1000)
    return () => clearTimeout(t)
  }, [left])

  async function resend() {
    setBusy(true)
    setError('')
    setNote('')
    try {
      const address = typeof email === 'string' ? email : await email()
      const sent = await api.resendVerification(address)
      setNote(sent.message)
      setLeft(RESEND_COOLDOWN_SECONDS)
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setError('Too many requests. Wait a minute and try again.')
        setLeft(RESEND_COOLDOWN_SECONDS)
      } else setError(err instanceof Error ? err.message : 'Could not send the link.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      <button type="button" className="outline" onClick={() => void resend()} disabled={busy || left > 0} data-testid="resend">
        {left > 0 ? `Send the link again (${left} s)` : 'Send the link again'}
      </button>
      <span role="status" aria-live="polite">{note && <small data-testid="resend-note">{note}</small>}</span>
      {error && <div role="alert" data-variant="danger">{error}</div>}
    </div>
  )
}
