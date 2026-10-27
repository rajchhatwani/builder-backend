import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../../api/client'
import { onSessionLost } from '../../api/session'
import { isMfaChallenge, type MfaChallenge, type UserAccount } from '../../api/types'
import { MfaStep } from '../../components/MfaStep'
import { useUi } from '../../components/Ui'
import {
  AdminAudit,
  AdminBilling,
  AdminInsightsPage,
  AdminOrgDetail,
  AdminOrganizations,
  AdminOverview,
  AdminPlans,
  AdminProjects,
  AdminSettings,
  AdminUsers,
} from './AdminPages'

export type AdminSection =
  | 'overview'
  | 'insights'
  | 'users'
  | 'organizations'
  | 'billing'
  | 'plans'
  | 'projects'
  | 'audit'
  | 'settings'

const SECTIONS: { id: AdminSection; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'insights', label: 'Insights' },
  { id: 'users', label: 'People' },
  { id: 'organizations', label: 'Organizations' },
  { id: 'billing', label: 'Billing' },
  { id: 'plans', label: 'Plans' },
  { id: 'projects', label: 'Projects' },
  { id: 'audit', label: 'Audit log' },
  { id: 'settings', label: 'Settings' },
]

export function parseAdminSection(hash: string): AdminSection {
  const match = hash.match(/^#\/admin\/?([a-z]*)/)
  return SECTIONS.find((s) => s.id === match?.[1])?.id ?? 'overview'
}

function AdminLogin({ onSignedIn }: { onSignedIn: (user: UserAccount) => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Platform staff always need a second factor (§4.4): a correct password asks for it.
  const [challenge, setChallenge] = useState<MfaChallenge | null>(null)

  const restart = useCallback((reason: string | null) => {
    setChallenge(null)
    setPassword('')
    setError(reason)
  }, [])

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const result = await api.adminLogin(email, password)
      if (isMfaChallenge(result)) setChallenge(result)
      else onSignedIn(result.user)
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.status === 429
            ? 'Too many attempts. Wait a few minutes.'
            : err.message
          : "Can't reach the server.",
      )
    } finally {
      setBusy(false)
    }
  }

  if (challenge) {
    return (
      <div className="auth-page admin-theme">
        <div className="card auth-card">
          <div className="admin-badge">Administration</div>
          <MfaStep
            challenge={challenge}
            steps={api.adminLoginMfa}
            onSignedIn={(session) => onSignedIn(session.user)}
            onRestart={restart}
          />
        </div>
      </div>
    )
  }

  return (
    <div className="auth-page admin-theme">
      <div className="card auth-card">
        <div className="admin-badge">Administration</div>
        <h2>Admin sign in</h2>
        <p className="muted small-text">
          For platform staff only. Customer accounts cannot sign in here.
        </p>
        <form onSubmit={submit}>
          {error && (
            <div role="alert" data-variant="danger">
              {error}
            </div>
          )}
          <label>
            Email
            <input type="email" required autoFocus autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label>
            Password
            <input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          <button type="submit" disabled={busy}>
            {busy ? 'Please wait…' : 'Sign in'}
          </button>
        </form>
        <p className="muted small-text auth-switch">
          <a href="#/">Back to the customer app</a>
        </p>
      </div>
    </div>
  )
}

/** The admin console: its own session, its own look, never mixed into the customer app. */
export function AdminApp({ section }: { section: AdminSection }) {
  const { toast } = useUi()
  const [user, setUser] = useState<UserAccount | null | undefined>(undefined)

  useEffect(() => {
    let cancelled = false
    api.adminResume().then((u) => !cancelled && setUser(u))
    const stop = onSessionLost((surface) => {
      if (surface === 'admin') {
        setUser(null)
        toast('Your admin session ended. Sign in again.', 'danger')
      }
    })
    return () => {
      cancelled = true
      stop()
    }
  }, [toast])

  if (user === undefined) return <p className="empty-state">Loading…</p>
  if (user === null) return <AdminLogin onSignedIn={setUser} />

  const readOnly = user.platform_role !== 'platform_admin'
  // #/admin/organizations/<id> opens one organization.
  const orgId = window.location.hash.match(/^#\/admin\/organizations\/([0-9a-f-]{36})/)?.[1]

  return (
    <>
      <nav data-topnav className="admin-band">
        <div className="row">
          <div className="col-6 branding">
            <span className="admin-badge">Administration</span>
            <span>Backend Builder</span>
          </div>
          <div className="col-6 justify-end hstack">
            <span className="muted small-text">
              {user.email} · {readOnly ? 'read-only' : 'admin'}
            </span>
            <a className="button outline small" href="#/">
              Customer app
            </a>
            <button
              className="outline small"
              onClick={async () => {
                await api.adminLogout()
                setUser(null)
              }}
            >
              Sign out
            </button>
          </div>
        </div>
      </nav>

      <aside data-sidebar className="main-sidebar">
        <nav>
          <ul>
            {SECTIONS.map((s) => (
              <li key={s.id}>
                <a href={`#/admin/${s.id}`} aria-current={section === s.id ? 'page' : undefined}>
                  <span>{s.label}</span>
                </a>
              </li>
            ))}
          </ul>
        </nav>
      </aside>

      <main>
        <div className="container">
          {section === 'overview' && <AdminOverview />}
          {section === 'users' && <AdminUsers me={user} readOnly={readOnly} />}
          {section === 'organizations' &&
            (orgId ? <AdminOrgDetail key={orgId} id={orgId} readOnly={readOnly} /> : <AdminOrganizations readOnly={readOnly} />)}
          {section === 'plans' && <AdminPlans readOnly={readOnly} />}
          {section === 'billing' && <AdminBilling readOnly={readOnly} />}
          {section === 'insights' && <AdminInsightsPage />}
          {section === 'projects' && <AdminProjects />}
          {section === 'audit' && <AdminAudit />}
          {section === 'settings' && <AdminSettings />}
        </div>
      </main>
    </>
  )
}
