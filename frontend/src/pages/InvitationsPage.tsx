import { useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import { notifyOrgsChanged } from '../api/orgEvents'
import type { OrgInvitation } from '../api/types'
import { useUser } from '../components/AuthProvider'
import { link } from '../components/Sidebar'
import { useUi } from '../components/Ui'

/** Accepts a pasted invite link (…#/invite/<token>) or the bare token. */
function tokenFrom(input: string): string {
  const value = input.trim()
  const match = value.match(/#\/invite\/([^/?#\s]+)/)
  return match ? decodeURIComponent(match[1]) : value
}

/**
 * `#/invitations` and `#/invite/<token>`: the signed-in user's open invitations (accept them
 * right here — the signed-in address is the proof) and the place an invite link lands.
 */
export function InvitationsPage({ token }: { token?: string }) {
  const me = useUser()
  const { toast } = useUi()
  const [pending, setPending] = useState<OrgInvitation[] | null>(null)
  const [pasted, setPasted] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .myPendingInvitations()
      .then((page) => !cancelled && setPending(page.items))
      .catch(() => !cancelled && setPending([]))
    return () => {
      cancelled = true
    }
  }, [])

  async function accept(raw: string) {
    await join(() => api.acceptInvitation(raw))
  }

  async function acceptById(id: string) {
    await join(() => api.acceptInvitationById(id))
  }

  async function join(call: () => Promise<{ name: string; slug: string }>) {
    setBusy(true)
    setError(null)
    try {
      const org = await call()
      notifyOrgsChanged()
      toast(`You joined ${org.name}.`)
      // Replace (not push) so the token doesn't stay in the back/forward history.
      window.location.replace(link(`/org/${encodeURIComponent(org.slug)}`))
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.status === 404
            ? `This invitation isn't valid for ${me.email}. It may have been revoked, or it was sent to another address.`
            : err.message
          : "Can't reach the server.",
      )
    } finally {
      setBusy(false)
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    accept(tokenFrom(pasted))
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Invitations</h1>
          <p>Join an organization you've been invited to. You're signed in as {me.email}.</p>
        </div>
      </div>

      {error && (
        <div role="alert" data-variant="danger">
          {error}
        </div>
      )}

      {token ? (
        <section className="card stack">
          <h3>You've been invited to an organization</h3>
          <p className="muted">
            Accepting adds you as a member with the role chosen by the person who invited you.
          </p>
          <div>
            <button disabled={busy} onClick={() => accept(token)}>
              {busy ? 'Joining…' : 'Accept invitation'}
            </button>
          </div>
        </section>
      ) : (
        <form className="card stack" onSubmit={submit}>
          <h3>Have an invite link?</h3>
          <label>
            Invite link
            <input value={pasted} onChange={(e) => setPasted(e.target.value)} placeholder="Paste the link you were sent" />
          </label>
          <div>
            <button type="submit" disabled={busy || !pasted.trim()}>
              {busy ? 'Joining…' : 'Join'}
            </button>
          </div>
        </form>
      )}

      <h2>Waiting for you</h2>
      {pending === null ? (
        <p className="empty-state">Loading…</p>
      ) : pending.length === 0 ? (
        <p className="muted">No open invitations for {me.email}.</p>
      ) : (
        <>
          <table>
            <thead>
              <tr>
                <th>Organization</th>
                <th>Role</th>
                <th>Expires</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {pending.map((inv) => (
                <tr key={inv.id}>
                  <td>{inv.organization_name || inv.organization_slug}</td>
                  <td>{inv.role}</td>
                  <td>{new Date(inv.expires_at).toLocaleDateString()}</td>
                  <td className="row-actions">
                    <button className="small" disabled={busy} onClick={() => acceptById(inv.id)}>
                      Accept
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small-text">
            Invitations sent to {me.email} can be accepted here, without the link.
          </p>
        </>
      )}
    </>
  )
}
