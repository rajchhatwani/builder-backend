import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import { useAuth } from './AuthProvider'
import { useUi } from './Ui'

function clock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

/**
 * The persistent "You are viewing as X" bar of a support session (§4.5). The operator can switch
 * changes on for a few minutes (audited), switch them off, or leave; the session also ends by
 * itself after ten minutes or when the organization withdraws its consent.
 */
export function ViewingBanner() {
  const { viewing, setViewing } = useAuth()
  const { toast } = useUi()
  const [now, setNow] = useState(() => Date.now())
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const tick = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(tick)
  }, [])

  const active = viewing !== null
  useEffect(() => {
    // leave room at the bottom of the page for the fixed bar
    document.body.classList.toggle('is-viewing', active)
    return () => document.body.classList.remove('is-viewing')
  }, [active])

  if (!viewing) return null
  const left = new Date(viewing.expires_at).getTime() - now
  const writesLeft = viewing.writes_until ? new Date(viewing.writes_until).getTime() - now : 0
  const writesOn = viewing.writes_allowed && writesLeft > 0

  async function setWrites(enabled: boolean) {
    setBusy(true)
    try {
      setViewing(await api.setImpersonationWrites(enabled))
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Can't reach the server.", 'danger')
    } finally {
      setBusy(false)
    }
  }

  async function exit() {
    setBusy(true)
    try {
      await api.endImpersonation()
    } catch {
      /* the session may already be over; either way we leave */
    }
    setViewing(null)
    window.close()
    // a tab the browser won't close: say so instead of leaving a dead app on screen
    document.body.innerHTML = '<p style="padding:2rem">Viewing session ended. You can close this tab.</p>'
  }

  return (
    <div className="viewing-banner" role="status">
      <span>
        <strong>You are viewing as {viewing.user_email}</strong> in {viewing.organization_name} · support session
        by {viewing.operator_email} · ends in {clock(left)}
      </span>
      <span className="hstack">
        {writesOn ? (
          <>
            <span>Changes allowed for {clock(writesLeft)}</span>
            <button className="small outline" disabled={busy} onClick={() => setWrites(false)}>
              Back to read-only
            </button>
          </>
        ) : (
          <>
            <span>Read-only</span>
            <button className="small outline" disabled={busy} onClick={() => setWrites(true)}>
              Allow changes for 5 min
            </button>
          </>
        )}
        <button className="small" data-variant="danger" disabled={busy} onClick={exit}>
          Exit
        </button>
      </span>
    </div>
  )
}
