import { useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import { useAuth } from './AuthProvider'
import { useUi } from './Ui'

/** Change the signed-in person's password; other devices are signed out by the server. */
export function PasswordForm({ onDone }: { onDone?: () => void }) {
  const { setUser } = useAuth()
  const { toast } = useUi()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (next !== repeat) {
      setError('The two new passwords are different.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const session = await api.changePassword(current, next)
      setUser(session.user)
      setCurrent('')
      setNext('')
      setRepeat('')
      toast('Password changed. Your other devices were signed out.')
      onDone?.()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Can't reach the server.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="stack">
      {error && (
        <div role="alert" data-variant="danger">
          {error}
        </div>
      )}
      <label>
        Current password
        <input
          type="password"
          required
          autoComplete="current-password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
        />
      </label>
      <label>
        New password
        <input
          type="password"
          required
          minLength={12}
          autoComplete="new-password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
        />
        <small className="muted">At least 12 characters, and not your email name or a common password.</small>
      </label>
      <label>
        Repeat new password
        <input
          type="password"
          required
          autoComplete="new-password"
          value={repeat}
          onChange={(e) => setRepeat(e.target.value)}
        />
      </label>
      <div>
        <button type="submit" disabled={busy}>
          {busy ? 'Saving…' : 'Change password'}
        </button>
      </div>
    </form>
  )
}
