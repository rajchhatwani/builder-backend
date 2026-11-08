import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../../api/client'
import type {
  AdminInsights,
  AdminOrg,
  AdminOrgMember,
  AdminOrgProject,
  AdminSubscription,
  AdminProject,
  AdminStats,
  AdminUser,
  ApiTokenInfo,
  ImpersonationDigest,
  ImpersonationSessionRow,
  AuditEntry,
  Page,
  PlatformRole,
  PlanInfo,
  PlanWrite,
  PlatformSettings,
  SsoCheck,
  UserAccount,
} from '../../api/types'
import { Modal } from '../../components/Modal'
import { openViewingTab } from '../../api/viewing'
import { useUi } from '../../components/Ui'
import { SsoChecklist } from '../OrgSsoTab'

const ROLE_LABEL: Record<PlatformRole, string> = {
  customer: 'Customer',
  platform_support: 'Support (read-only)',
  platform_admin: 'Administrator',
}

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : 'never'
}

function Header({ title, children }: { title: string; children?: string }) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {children && <p>{children}</p>}
      </div>
    </div>
  )
}

function Pager<T>({ page, onPage }: { page: Page<T>; onPage: (offset: number) => void }) {
  const from = page.total === 0 ? 0 : page.offset + 1
  const to = Math.min(page.offset + page.limit, page.total)
  return (
    <div className="table-toolbar">
      <span className="muted small-text">
        {from}–{to} of {page.total}
      </span>
      <span className="hstack">
        <button className="outline small" disabled={page.offset === 0} onClick={() => onPage(Math.max(0, page.offset - page.limit))}>
          Previous
        </button>
        <button className="outline small" disabled={to >= page.total} onClick={() => onPage(page.offset + page.limit)}>
          Next
        </button>
      </span>
    </div>
  )
}

// ── Overview ─────────────────────────────────────────────────────────────────

export function AdminOverview() {
  const [stats, setStats] = useState<AdminStats | null>(null)
  useEffect(() => {
    api.adminStats().then(setStats).catch(() => undefined)
  }, [])
  const cards: [string, number | undefined, string?][] = [
    ['People', stats?.users],
    ['Active', stats?.active_users],
    ['Suspended', stats?.suspended_users],
    ['Staff', stats?.admins],
    ['Projects', stats?.projects],
    ['Live API tokens', stats?.api_tokens],
    ['Failed sign-ins (24h)', stats?.failed_logins_24h, (stats?.failed_logins_24h ?? 0) > 50 ? 'status-warn' : undefined],
  ]
  return (
    <>
      <Header title="Overview">The state of the platform at a glance.</Header>
      <div className="stat-grid">
        {cards.map(([label, value, tone]) => (
          <div key={label} className={`card stat-card ${tone ?? ''}`}>
            <div className="stat-value">{value ?? '…'}</div>
            <div className="stat-label">{label}</div>
          </div>
        ))}
      </div>
      <div className="card">
        <h3>What administrators can and cannot do</h3>
        <ul>
          <li>Manage people: create, suspend, change platform role, reset passwords, end sessions.</li>
          <li>See project names, owners and sizes, and read the audit log.</li>
          <li>
            <strong>Cannot</strong> open a customer&apos;s data model, credentials or generated code. That line is deliberate.
          </li>
        </ul>
      </div>
    </>
  )
}

// ── People ───────────────────────────────────────────────────────────────────

function NewUserDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (u: AdminUser, temp: string | null) => void }) {
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [role, setRole] = useState<PlatformRole>('customer')
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    try {
      const created = await api.adminCreateUser({ email, name, platform_role: role })
      setEmail('')
      setName('')
      onCreated(created.user, created.temporary_password)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Can't reach the server.")
    }
  }

  return (
    <Modal open={open} onClose={onClose}>
      <form onSubmit={submit}>
        <header>
          <h3>New person</h3>
          <p>A temporary password is generated and shown once. They must change it at first sign-in.</p>
        </header>
        <div className="stack">
          {error && (
            <div role="alert" data-variant="danger">
              {error}
            </div>
          )}
          <label>
            Email
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label>
            Name
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            Platform role
            <select value={role} onChange={(e) => setRole(e.target.value as PlatformRole)}>
              {(Object.keys(ROLE_LABEL) as PlatformRole[]).map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABEL[r]}
                </option>
              ))}
            </select>
          </label>
        </div>
        <footer>
          <button type="button" className="outline" onClick={onClose}>
            Cancel
          </button>
          <button type="submit">Create</button>
        </footer>
      </form>
    </Modal>
  )
}

function UserTokensDialog({
  user,
  open,
  onClose,
}: {
  user: AdminUser | null
  open: boolean
  onClose: () => void
}) {
  const { confirm, toast } = useUi()
  const [tokens, setTokens] = useState<ApiTokenInfo[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!user) return
    setError(null)
    try {
      setTokens(await api.adminListUserTokens(user.id))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Can't load tokens.")
    }
  }, [user])

  useEffect(() => {
    if (open && user) {
      setTokens(null)
      load()
    }
  }, [open, user, load])

  async function revoke(t: ApiTokenInfo) {
    if (!user) return
    const ok = await confirm({
      title: `Revoke "${t.name}"?`,
      message: `Belongs to ${user.email}. Anything using it stops working immediately.`,
      confirmLabel: 'Revoke token',
      danger: true,
    })
    if (!ok) return
    try {
      await api.adminRevokeUserToken(user.id, t.id)
      toast('Token revoked.')
      await load()
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Can't revoke token.", 'danger')
    }
  }

  return (
    <Modal open={open} onClose={onClose}>
      <header>
        <h3>API tokens</h3>
        {user && <p className="muted small-text">{user.email}</p>}
      </header>
      <div className="stack">
        {error && (
          <div role="alert" data-variant="danger">
            {error}
          </div>
        )}
        {tokens === null ? (
          <p className="muted">Loading…</p>
        ) : tokens.length === 0 ? (
          <p className="muted">No tokens.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Scopes</th>
                <th>Last used</th>
                <th>Last MCP use</th>
                <th>State</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {tokens.map((t) => {
                const now = Date.now()
                const revoked = t.revoked_at !== null
                const expired = !revoked && new Date(t.expires_at).getTime() <= now
                const state = revoked ? 'revoked' : expired ? 'expired' : 'active'
                return (
                  <tr key={t.id}>
                    <td>
                      {t.name}
                      {t.description && <div className="muted small-text">{t.description}</div>}
                    </td>
                    <td>
                      <code className="small-text">{t.scopes.join(', ')}</code>
                    </td>
                    <td>{when(t.last_used_at)}</td>
                    <td>{when(t.last_mcp_use_at)}</td>
                    <td>
                      <span className={`badge ${state === 'active' ? 'status-ok' : 'status-warn'}`}>
                        {state}
                      </span>
                    </td>
                    <td className="row-actions">
                      {state === 'active' && (
                        <button className="ghost small" data-variant="danger" onClick={() => revoke(t)}>
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
      <footer>
        <button type="button" onClick={onClose}>
          Done
        </button>
      </footer>
    </Modal>
  )
}

/** Platform admins only (§4.4): clears TOTP + recovery codes and ends every session. */
function ResetMfaDialog({ user, onClose, onDone }: { user: AdminUser; onClose: () => void; onDone: (u: AdminUser) => void }) {
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onDone(await api.adminResetMfa(user.id, reason.trim()))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Can't reach the server.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open onClose={onClose}>
      <form onSubmit={submit}>
        <header>
          <h3>Reset two-factor for {user.email}?</h3>
          <p>
            Their authenticator and recovery codes stop working and they are signed out everywhere.
            {user.platform_role !== 'customer' && ' As platform staff, they set up two-factor again at their next sign-in.'} Only
            do this after confirming who is asking.
          </p>
        </header>
        <div className="stack">
          {error && (
            <div role="alert" data-variant="danger">
              {error}
            </div>
          )}
          <label>
            Reason (recorded in the audit log)
            <input required maxLength={255} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Lost phone, identity checked by video call" />
          </label>
        </div>
        <footer>
          <button type="button" className="outline" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" data-variant="danger" disabled={busy || !reason.trim()}>
            {busy ? 'Resetting…' : 'Reset two-factor'}
          </button>
        </footer>
      </form>
    </Modal>
  )
}

export function AdminUsers({ me, readOnly }: { me: UserAccount; readOnly: boolean }) {
  const { confirm, toast } = useUi()
  const [page, setPage] = useState<Page<AdminUser> | null>(null)
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [role, setRole] = useState('')
  const [offset, setOffset] = useState(0)
  const [creating, setCreating] = useState(false)
  const [secret, setSecret] = useState<{ email: string; password: string } | null>(null)
  const [tokensUser, setTokensUser] = useState<AdminUser | null>(null)
  const [resetting, setResetting] = useState<AdminUser | null>(null)

  const load = useCallback(async () => {
    setPage(await api.adminUsers({ q, status, role, limit: 25, offset }))
  }, [q, status, role, offset])

  useEffect(() => {
    const timer = setTimeout(() => load().catch(() => undefined), 200)
    return () => clearTimeout(timer)
  }, [load])

  async function run(action: () => Promise<unknown>, done: string) {
    try {
      await action()
      toast(done)
      await load()
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Can't reach the server.", 'danger')
    }
  }

  async function suspendOrRestore(u: AdminUser) {
    const suspend = u.status === 'active'
    if (suspend) {
      const ok = await confirm({
        title: `Suspend ${u.email}?`,
        message: 'They are signed out everywhere and cannot sign in until restored.',
        confirmLabel: 'Suspend',
        danger: true,
      })
      if (!ok) return
    }
    await run(() => api.adminUpdateUser(u.id, { status: suspend ? 'suspended' : 'active' }), suspend ? 'Suspended.' : 'Restored.')
  }

  async function resetPassword(u: AdminUser) {
    const ok = await confirm({
      title: `Reset the password of ${u.email}?`,
      message: 'Their sessions end and a new temporary password is shown once.',
      confirmLabel: 'Reset password',
      danger: true,
    })
    if (!ok) return
    try {
      const { temporary_password } = await api.adminResetPassword(u.id)
      setSecret({ email: u.email, password: temporary_password })
      await load()
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Can't reach the server.", 'danger')
    }
  }

  return (
    <>
      <Header title="People">Everyone with an account on the platform.</Header>

      {secret && (
        <div role="alert" data-variant="success" className="stack">
          <strong>Temporary password for {secret.email}. It will not be shown again.</strong>
          <code className="token-box">{secret.password}</code>
          <div>
            <button className="small" onClick={() => navigator.clipboard.writeText(secret.password).then(() => toast('Copied.'))}>
              Copy
            </button>{' '}
            <button className="outline small" onClick={() => setSecret(null)}>
              Done
            </button>
          </div>
        </div>
      )}

      <div className="table-toolbar">
        <div className="hstack">
          <input type="search" placeholder="Search email or name" value={q} onChange={(e) => { setOffset(0); setQ(e.target.value) }} />
          <select aria-label="Status" value={status} onChange={(e) => { setOffset(0); setStatus(e.target.value) }}>
            <option value="">Any status</option>
            <option value="active">Active</option>
            <option value="suspended">Suspended</option>
          </select>
          <select aria-label="Platform role" value={role} onChange={(e) => { setOffset(0); setRole(e.target.value) }}>
            <option value="">Any role</option>
            {(Object.keys(ROLE_LABEL) as PlatformRole[]).map((r) => (
              <option key={r} value={r}>
                {ROLE_LABEL[r]}
              </option>
            ))}
          </select>
        </div>
        {!readOnly && <button onClick={() => setCreating(true)}>New person</button>}
      </div>

      {page && (
        <>
          <table>
            <thead>
              <tr>
                <th>Person</th>
                <th>Role</th>
                <th>Status</th>
                <th>2FA</th>
                <th>Projects</th>
                <th>Last sign-in</th>
                {!readOnly && <th />}
              </tr>
            </thead>
            <tbody>
              {page.items.map((u) => {
                const self = u.id === me.id
                return (
                  <tr key={u.id}>
                    <td>
                      {u.email}
                      {self && <span className="muted"> (you)</span>}
                      {u.name && <div className="muted small-text">{u.name}</div>}
                    </td>
                    <td>
                      {readOnly || self ? (
                        ROLE_LABEL[u.platform_role]
                      ) : (
                        <select
                          aria-label={`Role of ${u.email}`}
                          value={u.platform_role}
                          onChange={(e) => run(() => api.adminUpdateUser(u.id, { platform_role: e.target.value as PlatformRole }), 'Role updated.')}
                        >
                          {(Object.keys(ROLE_LABEL) as PlatformRole[]).map((r) => (
                            <option key={r} value={r}>
                              {ROLE_LABEL[r]}
                            </option>
                          ))}
                        </select>
                      )}
                    </td>
                    <td>
                      <span className={`badge ${u.status === 'active' ? 'status-ok' : 'status-warn'}`}>{u.status}</span>
                      {u.locked_until && new Date(u.locked_until) > new Date() && <span className="badge status-warn">locked</span>}
                      {u.must_change_password && <span className="badge">temp password</span>}
                    </td>
                    <td>
                      <span className={`badge ${u.mfa_enabled ? 'status-ok' : 'badge-muted'}`}>{u.mfa_enabled ? 'on' : 'off'}</span>
                    </td>
                    <td>{u.project_count}</td>
                    <td>{when(u.last_login_at)}</td>
                    {!readOnly && (
                      <td className="row-actions">
                        <button className="ghost small" onClick={() => setTokensUser(u)}>
                          Tokens
                        </button>
                        {!self && (
                          <>
                            <button className="ghost small" onClick={() => suspendOrRestore(u)}>
                              {u.status === 'active' ? 'Suspend' : 'Restore'}
                            </button>
                            <button className="ghost small" onClick={() => run(() => api.adminRevokeSessions(u.id), 'Signed out everywhere.')}>
                              End sessions
                            </button>
                            <button className="ghost small" data-variant="danger" onClick={() => resetPassword(u)}>
                              Reset password
                            </button>
                            {u.mfa_enabled && (
                              <button className="ghost small" data-variant="danger" onClick={() => setResetting(u)}>
                                Reset 2FA
                              </button>
                            )}
                          </>
                        )}
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
          <Pager page={page} onPage={setOffset} />
        </>
      )}

      {resetting && (
        <ResetMfaDialog
          user={resetting}
          onClose={() => setResetting(null)}
          onDone={(u) => {
            setResetting(null)
            toast(`Two-factor reset for ${u.email}. They were signed out everywhere.`)
            load().catch(() => undefined)
          }}
        />
      )}

      <UserTokensDialog
        open={tokensUser !== null}
        user={tokensUser}
        onClose={() => setTokensUser(null)}
      />

      <NewUserDialog
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(user, temp) => {
          setCreating(false)
          if (temp) setSecret({ email: user.email, password: temp })
          load()
        }}
      />
    </>
  )
}

// ── Projects (metadata only) ─────────────────────────────────────────────────

export function AdminProjects() {
  const [page, setPage] = useState<Page<AdminProject> | null>(null)
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)
  useEffect(() => {
    const timer = setTimeout(() => api.adminProjects(q, 25, offset).then(setPage).catch(() => undefined), 200)
    return () => clearTimeout(timer)
  }, [q, offset])
  return (
    <>
      <Header title="Projects">Names, owners and size only. Customer data is not visible here.</Header>
      <div className="table-toolbar">
        <input type="search" placeholder="Search name or slug" value={q} onChange={(e) => { setOffset(0); setQ(e.target.value) }} />
      </div>
      {page && (
        <>
          <table>
            <thead>
              <tr>
                <th>Project</th>
                <th>Owners</th>
                <th>Entities</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((p) => (
                <tr key={p.id}>
                  <td>
                    {p.name} <span className="muted small-text">{p.slug}</span>
                  </td>
                  <td>{p.owner_emails.length ? p.owner_emails.join(', ') : <span className="muted">unclaimed</span>}</td>
                  <td>{p.entity_count}</td>
                  <td>{when(p.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager page={page} onPage={setOffset} />
        </>
      )}
    </>
  )
}

// ── Organizations: plan + seat/project overrides (§6.5) ─────────────────────

function numberOrNull(value: string): number | null {
  return value.trim() === '' ? null : Number(value)
}

function OverrideDialog({ org, onClose, onSaved }: { org: AdminOrg; onClose: () => void; onSaved: (org: AdminOrg) => void }) {
  const [seats, setSeats] = useState(org.seat_override?.toString() ?? '')
  const [projects, setProjects] = useState(org.project_override?.toString() ?? '')
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onSaved(
        await api.adminSetOrgOverrides(org.id, {
          seat_override: numberOrNull(seats),
          project_override: numberOrNull(projects),
          reason: reason.trim(),
        }),
      )
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Can't reach the server.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open onClose={onClose}>
      <form onSubmit={submit}>
        <header>
          <h3>Limits for {org.name}</h3>
          <p>Replaces the {org.plan_id} plan's cap for this organization. Leave empty to use the plan default.</p>
        </header>
        <div>
          {error && (
            <div role="alert" data-variant="danger">
              {error}
            </div>
          )}
          <label>
            Seats
            <input type="number" min={0} placeholder="plan default" value={seats} onChange={(e) => setSeats(e.target.value)} />
          </label>
          <label>
            Projects
            <input type="number" min={0} placeholder="plan default" value={projects} onChange={(e) => setProjects(e.target.value)} />
          </label>
          <label>
            Reason (recorded in the audit log)
            <input required maxLength={255} value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
        </div>
        <footer>
          <button type="button" className="outline" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" disabled={busy || !reason.trim()}>
            {busy ? 'Saving…' : 'Save limits'}
          </button>
        </footer>
      </form>
    </Modal>
  )
}

export function AdminOrganizations({ readOnly }: { readOnly: boolean }) {
  const { toast } = useUi()
  const [page, setPage] = useState<Page<AdminOrg> | null>(null)
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)
  const [editing, setEditing] = useState<AdminOrg | null>(null)
  useEffect(() => {
    const timer = setTimeout(() => api.adminOrganizations(q, 25, offset).then(setPage).catch(() => undefined), 200)
    return () => clearTimeout(timer)
  }, [q, offset])

  function saved(org: AdminOrg) {
    setEditing(null)
    setPage((current) => current && { ...current, items: current.items.map((o) => (o.id === org.id ? org : o)) })
    toast(`Limits updated for ${org.name}.`)
  }

  return (
    <>
      <Header title="Organizations">Plan, size and granted overrides. Project contents are not visible here.</Header>
      <div className="table-toolbar">
        <input type="search" placeholder="Search name or slug" value={q} onChange={(e) => { setOffset(0); setQ(e.target.value) }} />
      </div>
      {page && (
        <>
          <table>
            <thead>
              <tr>
                <th>Organization</th>
                <th>Plan</th>
                <th>Members</th>
                <th>Projects</th>
                <th>MRR</th>
                <th>Last activity</th>
                <th>SSO</th>
                <th>SCIM</th>
                <th>Overrides</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {page.items.map((o) => (
                <tr key={o.id}>
                  <td>
                    <a href={`#/admin/organizations/${o.id}`}>{o.name}</a>{' '}
                    <span className="muted small-text">{o.slug}{o.kind === 'personal' ? ' · personal' : ''}</span>
                    {o.deletion_scheduled_for && (
                      <div className="small-text status-warn">Deletion requested · deletes {when(o.deletion_scheduled_for)}</div>
                    )}
                  </td>
                  <td>
                    {o.plan_id} <span className="muted small-text">{o.status}</span>
                  </td>
                  <td>{o.member_count}</td>
                  <td>{o.project_count}</td>
                  <td>{o.mrr_cents ? `$${(o.mrr_cents / 100).toFixed(0)}` : <span className="muted">—</span>}</td>
                  <td className="small-text">{when(o.last_activity_at)}</td>
                  <td className="small-text">
                    <SsoStatus org={o} />
                  </td>
                  <td className="small-text">
                    <ScimStatus org={o} />
                  </td>
                  <td className="small-text">
                    {o.seat_override === null && o.project_override === null ? (
                      <span className="muted">none</span>
                    ) : (
                      [o.seat_override !== null && `${o.seat_override} seats`, o.project_override !== null && `${o.project_override} projects`]
                        .filter(Boolean)
                        .join(', ')
                    )}
                  </td>
                  <td>
                    {!readOnly && (
                      <button className="outline small" onClick={() => setEditing(o)}>
                        Limits
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager page={page} onPage={setOffset} />
        </>
      )}
      {editing && <OverrideDialog org={editing} onClose={() => setEditing(null)} onSaved={saved} />}
      {!readOnly && <SupportDigest />}
    </>
  )
}

/** §4.5: what the daily support-access digest would say (the cron job sends it; this only shows it). */
function SupportDigest() {
  const [hours, setHours] = useState(24)
  const [digest, setDigest] = useState<ImpersonationDigest | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let cancelled = false
    api
      .adminImpersonationDigest(hours)
      .then((d) => !cancelled && (setDigest(d), setFailed(false)))
      .catch(() => !cancelled && setFailed(true))
    return () => {
      cancelled = true
    }
  }, [hours])
  return (
    <section className="card stack" data-testid="support-digest">
      <h3>Support access digest</h3>
      <p className="muted small-text">
        Every "view as" session in the period, as the daily security digest reports it. The digest is sent by the
        scheduled job; this is a preview and sends nothing.
      </p>
      <label>
        Period
        <select value={hours} onChange={(e) => setHours(Number(e.target.value))}>
          <option value={24}>Last 24 hours</option>
          <option value={72}>Last 3 days</option>
          <option value={168}>Last 7 days</option>
        </select>
      </label>
      {failed ? <p className="muted">Can't load the digest.</p> : <pre className="small-text">{digest?.text ?? 'Loading…'}</pre>}
    </section>
  )
}

// ── Organization detail (§7): plan change, limits, audit tail ───────────────

/** "SAML · on", "OIDC · off", or a dash when the org has no SSO connection. */
function SsoStatus({ org }: { org: AdminOrg }) {
  if (!org.sso_protocol) return <span className="muted">—</span>
  return (
    <span title={org.sso_last_test_result ? `Last test: ${org.sso_last_test_result} (${when(org.sso_last_test_at ?? null)})` : 'Never tested'}>
      {org.sso_protocol.toUpperCase()} · {org.sso_active ? 'on' : 'off'}
    </span>
  )
}

/** "on · 12 users", "off", or a dash when the org has no SCIM directory. */
function ScimStatus({ org }: { org: AdminOrg }) {
  if (!org.scim_configured) return <span className="muted">—</span>
  const users = org.scim_users ?? 0
  return (
    <span title={org.scim_last_sync_at ? `Last sync: ${when(org.scim_last_sync_at)}` : 'The IdP has not synced yet'}>
      {org.scim_active ? `on · ${users} user${users === 1 ? '' : 's'}` : 'off'}
    </span>
  )
}

/** Audit "who": the IdP writes SCIM rows without an actor. */
function auditActor(e: AuditEntry) {
  return e.actor_email ?? <span className="muted">{e.via === 'scim' ? 'SCIM' : 'system'}</span>
}

function AuditTable({ items }: { items: AuditEntry[] }) {
  return (
    <table>
      <thead>
        <tr>
          <th>When</th>
          <th>Who</th>
          <th>What</th>
          <th>Outcome</th>
        </tr>
      </thead>
      <tbody>
        {items.map((e) => (
          <tr key={e.id}>
            <td>{when(e.at)}</td>
            <td>{auditActor(e)}</td>
            <td>
              {e.action}
              {e.detail && <div className="muted small-text">{Object.entries(e.detail).map(([k, v]) => `${k}: ${String(v)}`).join(' · ')}</div>}
            </td>
            <td>
              <span className={`badge ${e.result === 'ok' ? 'status-ok' : 'status-warn'}`}>{e.result}</span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** Operator actions on a pending deletion request: a new grace period, or delete right away. */
function DeletionDialog({
  org,
  mode,
  onClose,
  onDone,
}: {
  org: AdminOrg
  mode: 'reschedule' | 'execute'
  onClose: () => void
  onDone: (org: AdminOrg) => void
}) {
  const [days, setDays] = useState('7')
  const [reason, setReason] = useState('')
  const [confirmName, setConfirmName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const execute = mode === 'execute'
  const daysValid = /^\d+$/.test(days) && Number(days) <= 3650

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onDone(
        execute
          ? await api.adminExecuteOrgDeletion(org.id, reason.trim())
          : await api.adminRescheduleOrgDeletion(org.id, Number(days), reason.trim()),
      )
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Can't reach the server.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open onClose={onClose}>
      <form onSubmit={submit}>
        <header>
          <h3>{execute ? `Delete ${org.name} now?` : `Change the deletion date of ${org.name}`}</h3>
          <p>
            {execute
              ? `This deletes the organization and all ${org.project_count} of its projects immediately, instead of on ${when(org.deletion_scheduled_for ?? null)}. It cannot be undone.`
              : 'The new grace period counts from now. 0 days means it is deleted the next time the deletion job runs.'}
          </p>
        </header>
        <div>
          {error && (
            <div role="alert" data-variant="danger">
              {error}
            </div>
          )}
          {!execute && (
            <label>
              Grace period (days from now)
              <input type="number" min={0} max={3650} required value={days} onChange={(e) => setDays(e.target.value)} />
            </label>
          )}
          <label>
            Reason (recorded in the audit log)
            <input required maxLength={255} value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          {execute && (
            <label>
              Type the organization's slug, <code>{org.slug}</code>, to confirm
              <input value={confirmName} onChange={(e) => setConfirmName(e.target.value)} autoComplete="off" />
            </label>
          )}
        </div>
        <footer>
          <button type="button" className="outline" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            data-variant={execute ? 'danger' : undefined}
            disabled={busy || !reason.trim() || (execute ? confirmName !== org.slug : !daysValid)}
          >
            {busy ? 'Saving…' : execute ? 'Delete now' : 'Change date'}
          </button>
        </footer>
      </form>
    </Modal>
  )
}

/** §12.E.4: replace a (possibly leaked) SCIM token with one nobody sees (§7.1). */
/** §4.5: ask for a reason, mint the ten-minute token, hand it to a new tab. Platform admins only. */
function ViewAsDialog({
  org,
  member,
  onClose,
  onStarted,
}: {
  org: AdminOrg
  member: AdminOrgMember
  onClose: () => void
  onStarted: () => void
}) {
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const started = await api.adminImpersonate(org.id, member.user_id, reason.trim())
      const opened = await openViewingTab(started.access_token)
      if (!opened) {
        await api.adminEndImpersonation(started.session_id).catch(() => undefined)
        setError('The browser blocked the new tab. Allow pop-ups for this site and try again.')
        return
      }
      onStarted()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Can't reach the server.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open onClose={onClose}>
      <form onSubmit={submit}>
        <header>
          <h3>View as {member.name || member.email}?</h3>
          <p>
            Opens a new tab that shows {org.name} as this person sees it. It lasts ten minutes, starts read-only, and every
            request is recorded in {org.name}'s audit log. You will never see credentials, tokens or billing.
          </p>
        </header>
        <div>
          {error && (
            <div role="alert" data-variant="danger">
              {error}
            </div>
          )}
          <label>
            Reason (recorded; the customer can see it)
            <input
              required
              minLength={5}
              maxLength={200}
              placeholder="Ticket number or what you are helping with"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
        </div>
        <footer>
          <button type="button" className="outline" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" disabled={busy || reason.trim().length < 5}>
            {busy ? 'Starting…' : 'Start viewing'}
          </button>
        </footer>
      </form>
    </Modal>
  )
}

function RotateScimDialog({ org, onClose, onDone }: { org: AdminOrg; onClose: () => void; onDone: (org: AdminOrg) => void }) {
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onDone(await api.adminRotateScim(org.id, reason.trim()))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Can't reach the server.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open onClose={onClose}>
      <form onSubmit={submit}>
        <header>
          <h3>Rotate the SCIM token of {org.name}?</h3>
          <p>
            The current token stops working immediately. The new token is not shown to anyone. SCIM is switched off until
            an org admin generates a new token, which switches it back on.
          </p>
        </header>
        <div>
          {error && (
            <div role="alert" data-variant="danger">
              {error}
            </div>
          )}
          <label>
            Reason (recorded in the audit log)
            <input required maxLength={255} value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
        </div>
        <footer>
          <button type="button" className="outline" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" data-variant="danger" disabled={busy || !reason.trim()}>
            {busy ? 'Rotating…' : 'Rotate token'}
          </button>
        </footer>
      </form>
    </Modal>
  )
}

export function AdminOrgDetail({ id, readOnly }: { id: string; readOnly: boolean }) {
  const { confirm, toast } = useUi()
  const [org, setOrg] = useState<AdminOrg | null>(null)
  const [plans, setPlans] = useState<PlanInfo[]>([])
  const [audit, setAudit] = useState<Page<AuditEntry> | null>(null)
  const [auditOffset, setAuditOffset] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [planId, setPlanId] = useState('')
  const [planReason, setPlanReason] = useState('')
  const [members, setMembers] = useState<AdminOrgMember[]>([])
  const [projects, setProjects] = useState<AdminOrgProject[]>([])
  const [deletion, setDeletion] = useState<'reschedule' | 'execute' | null>(null)
  const [ssoCheck, setSsoCheck] = useState<SsoCheck | null>(null)
  const [checking, setChecking] = useState(false)
  const [rotatingScim, setRotatingScim] = useState(false)
  const [viewAs, setViewAs] = useState<AdminOrgMember | null>(null)
  const [sessions, setSessions] = useState<ImpersonationSessionRow[]>([])

  useEffect(() => {
    let cancelled = false
    Promise.all([api.adminOrganization(id), api.adminPlans(), api.adminOrgMembers(id), api.adminOrgProjects(id)])
      .then(([o, p, m, pr]) => {
        if (cancelled) return
        setOrg(o)
        setPlanId(o.plan_id)
        setPlans(p)
        setMembers(m)
        setProjects(pr)
      })
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err.message : "Can't reach the server."))
    return () => {
      cancelled = true
    }
  }, [id])

  const loadSessions = useCallback(() => {
    api
      .adminImpersonationSessions({ organization_id: id, limit: 10 })
      .then((page) => setSessions(page.items))
      .catch(() => undefined) // support staff can't list them; the section just stays hidden
  }, [id])

  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  useEffect(() => {
    let cancelled = false
    api
      .adminAudit({ organization_id: id, limit: 25, offset: auditOffset })
      .then((page) => !cancelled && setAudit(page))
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [id, auditOffset])

  if (error) return <div role="alert" data-variant="danger">{error}</div>
  if (!org) return <p className="empty-state">Loading…</p>

  async function changePlan() {
    if (!org || planId === org.plan_id || !planReason.trim()) return
    const ok = await confirm({
      title: `Move ${org.name} to ${planId}?`,
      message: 'The new caps apply immediately. The reason is recorded in the audit log.',
      confirmLabel: 'Change plan',
      danger: true,
    })
    if (!ok) {
      setPlanId(org.plan_id)
      return
    }
    try {
      const updated = await api.adminSetOrgPlan(org.id, planId, planReason.trim())
      setPlanReason('')
      setOrg(updated)
      setAuditOffset(0)
      setAudit(null)
      api.adminAudit({ organization_id: id, limit: 25, offset: 0 }).then(setAudit).catch(() => undefined)
      toast(`${updated.name} is now on ${updated.plan_id}.`)
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Can't reach the server.", 'danger')
      setPlanId(org.plan_id)
    }
  }

  async function runSsoCheck() {
    setChecking(true)
    try {
      setSsoCheck(await api.adminCheckSso(id))
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Can't reach the server.", 'danger')
    } finally {
      setChecking(false)
    }
  }

  return (
    <>
      <a className="breadcrumb-back" href="#/admin/organizations">
        ← All organizations
      </a>
      <div className="page-header">
        <div>
          <h1>{org.name}</h1>
          <p>
            {org.slug} · {org.kind} · created {when(org.created_at)}
            {org.deleted_at && <span className="status-warn"> · deleted {when(org.deleted_at)}</span>}
          </p>
        </div>
      </div>

      {org.deletion_scheduled_for && !org.deleted_at && (
        <div role="alert" data-variant="warning" className="stack">
          <strong>
            The owner asked to delete this organization on {when(org.deletion_requested_at ?? null)}. It is locked and
            will be deleted, with its {org.project_count} project{org.project_count === 1 ? '' : 's'}, on{' '}
            {when(org.deletion_scheduled_for)}.
          </strong>
          <span className="small-text">Only the owner can cancel the request.</span>
          {!readOnly && (
            <div className="hstack">
              <button className="outline small" onClick={() => setDeletion('reschedule')}>
                Change period
              </button>
              <button className="small" data-variant="danger" onClick={() => setDeletion('execute')}>
                Delete now
              </button>
            </div>
          )}
        </div>
      )}

      <div className="stat-grid">
        <div className="card stat-card">
          <div className="stat-value">{org.plan_id || '—'}</div>
          <div className="stat-label">Plan · {org.status || 'no subscription'}</div>
        </div>
        <div className="card stat-card">
          <div className="stat-value">{org.member_count}</div>
          <div className="stat-label">Members{org.seat_override !== null ? ` · ${org.seat_override} seat override` : ''}</div>
        </div>
        <div className="card stat-card">
          <div className="stat-value">{org.project_count}</div>
          <div className="stat-label">Projects{org.project_override !== null ? ` · ${org.project_override} project override` : ''}</div>
        </div>
        <div className="card stat-card">
          <div className="stat-value">${(org.mrr_cents / 100).toFixed(0)}</div>
          <div className="stat-label">MRR · last activity {when(org.last_activity_at)}</div>
        </div>
      </div>

      {org.stripe_customer_id && (
        <p className="small-text">
          Billed through Stripe:{' '}
          <a href={`https://dashboard.stripe.com/customers/${org.stripe_customer_id}`} target="_blank" rel="noreferrer">
            customer {org.stripe_customer_id}
          </a>
          {org.stripe_subscription_id && (
            <>
              {' · '}
              <a href={`https://dashboard.stripe.com/subscriptions/${org.stripe_subscription_id}`} target="_blank" rel="noreferrer">
                subscription
              </a>
            </>
          )}
          {org.current_period_end && <> · renews {when(org.current_period_end)}</>}
        </p>
      )}

      {!readOnly && (
        <section className="card stack">
          <h3>Plan and limits</h3>
          <div className="hstack">
            <select
              aria-label="Plan"
              value={planId}
              disabled={!!org.stripe_subscription_id}
              onChange={(e) => setPlanId(e.target.value)}
            >
              {plans.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.display_name} ({p.id})
                </option>
              ))}
            </select>
            {!org.stripe_subscription_id && planId !== org.plan_id && (
              <input
                aria-label="Reason for the plan change"
                placeholder="Reason (audited)"
                maxLength={255}
                value={planReason}
                onChange={(e) => setPlanReason(e.target.value)}
              />
            )}
            <button disabled={planId === org.plan_id || !planReason.trim()} onClick={changePlan}>
              Change plan
            </button>
            <button className="outline" onClick={() => setEditing(true)}>
              Seat / project limits
            </button>
          </div>
          <p className="muted small-text">
            {org.stripe_subscription_id
              ? 'This organization pays through Stripe, so its plan follows Stripe. Change it in the Stripe Dashboard.'
              : 'Both changes are recorded in the audit log below.'}
          </p>
        </section>
      )}

      <section className="card stack">
        <div className="table-toolbar">
          <h3>Single sign-on and security</h3>
          {org.kind === 'team' && (
            <button className="outline small" disabled={checking} onClick={runSsoCheck}>
              {checking ? 'Checking…' : 'Check SSO'}
            </button>
          )}
        </div>
        <p className="small-text">
          SSO: <SsoStatus org={org} />
          {org.sso_protocol && (
            <>
              {' '}
              · {org.sso_verified_domains ?? 0} verified domain{org.sso_verified_domains === 1 ? '' : 's'} · last test{' '}
              {org.sso_last_test_result ? `${org.sso_last_test_result} (${when(org.sso_last_test_at ?? null)})` : 'never'}
            </>
          )}
        </p>
        <div className="table-toolbar small-text">
          <span>
            SCIM: <ScimStatus org={org} />
            {org.scim_configured && (
              <>
                {' '}
                · last sync {when(org.scim_last_sync_at ?? null)} · token created {when(org.scim_token_created_at ?? null)}
              </>
            )}
          </span>
          {org.scim_configured && !readOnly && (
            <button className="outline small" data-variant="danger" onClick={() => setRotatingScim(true)}>
              Rotate SCIM token
            </button>
          )}
        </div>
        <p className="small-text">
          Two-factor required: {org.require_mfa ? 'yes' : 'no'} · Session length:{' '}
          {org.session_ttl_hours ? `${org.session_ttl_hours} h` : 'platform default'}
        </p>
        <p className="muted small-text">
          The check reads the configuration and fetches the identity provider's public documents. It can't sign anyone
          in; the customer runs a real test from their SSO settings.
        </p>
        {ssoCheck && <SsoChecklist check={ssoCheck} />}
      </section>

      <h2>Members</h2>
      {!org.allow_impersonation && (
        <p className="muted small-text">
          This organization has turned off support access ("view as"). Only its admins can turn it back on.
        </p>
      )}
      <table>
        <thead>
          <tr>
            <th>Member</th>
            <th>Role</th>
            <th>Status</th>
            <th>2FA</th>
            <th>Last sign-in</th>
            {!readOnly && <th />}
          </tr>
        </thead>
        <tbody>
          {members.map((m) => (
            <tr key={m.user_id}>
              <td>
                {m.name || m.email} {m.name && <span className="muted small-text">{m.email}</span>}
              </td>
              <td>{m.role}</td>
              <td>{m.status}</td>
              <td>{m.mfa_enabled ? 'on' : 'off'}</td>
              <td>{when(m.last_login_at)}</td>
              {!readOnly && (
                <td>
                  <button
                    className="outline small"
                    disabled={!org.allow_impersonation || m.status !== 'active'}
                    title={org.allow_impersonation ? 'Open a read-only support session as this person' : 'The organization has not allowed this'}
                    onClick={() => setViewAs(m)}
                  >
                    View as
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>

      {sessions.length > 0 && (
        <>
          <h2>Support sessions</h2>
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>Operator</th>
                <th>Viewed as</th>
                <th>Reason</th>
                <th>State</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((x) => (
                <tr key={x.id}>
                  <td>{when(x.created_at)}</td>
                  <td>{x.operator_email}</td>
                  <td>{x.user_email}</td>
                  <td>{x.reason}</td>
                  <td>
                    {x.active ? (
                      <>
                        active{' '}
                        {!readOnly && (
                          <button
                            className="outline small"
                            onClick={() =>
                              api
                                .adminEndImpersonation(x.id)
                                .then(loadSessions)
                                .catch(() => undefined)
                            }
                          >
                            End
                          </button>
                        )}
                      </>
                    ) : (
                      'ended'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      <h2>Projects</h2>
      <p className="muted small-text">Metadata only. Project contents are not visible here.</p>
      {projects.length === 0 ? (
        <p className="muted">No projects.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Project</th>
              <th>Entities</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {projects.map((p) => (
              <tr key={p.id}>
                <td>
                  {p.name} <span className="muted small-text">{p.slug}</span>
                </td>
                <td>{p.entity_count}</td>
                <td>{when(p.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Audit trail</h2>
      {audit === null ? (
        <p className="empty-state">Loading…</p>
      ) : audit.items.length === 0 ? (
        <p className="muted">No events recorded for this organization.</p>
      ) : (
        <>
          <AuditTable items={audit.items} />
          <Pager page={audit} onPage={setAuditOffset} />
        </>
      )}

      {viewAs && (
        <ViewAsDialog
          org={org}
          member={viewAs}
          onClose={() => setViewAs(null)}
          onStarted={() => {
            setViewAs(null)
            loadSessions()
            setAuditOffset(0)
            api.adminAudit({ organization_id: id, limit: 25, offset: 0 }).then(setAudit).catch(() => undefined)
            toast('Support session opened in a new tab.')
          }}
        />
      )}

      {rotatingScim && (
        <RotateScimDialog
          org={org}
          onClose={() => setRotatingScim(false)}
          onDone={(updated) => {
            setRotatingScim(false)
            setOrg(updated)
            setAuditOffset(0)
            api.adminAudit({ organization_id: id, limit: 25, offset: 0 }).then(setAudit).catch(() => undefined)
            toast(`SCIM token of ${updated.name} rotated. SCIM is off until an org admin generates a new token.`)
          }}
        />
      )}

      {deletion && (
        <DeletionDialog
          org={org}
          mode={deletion}
          onClose={() => setDeletion(null)}
          onDone={(updated) => {
            if (deletion === 'execute') {
              // Members, invitations and projects are gone with the organization.
              setMembers([])
              setProjects([])
            }
            setDeletion(null)
            setOrg(updated)
            toast(
              deletion === 'execute'
                ? `${updated.name} was deleted.`
                : `${updated.name} will now be deleted on ${when(updated.deletion_scheduled_for ?? null)}.`,
            )
          }}
        />
      )}

      {editing && (
        <OverrideDialog
          org={org}
          onClose={() => setEditing(false)}
          onSaved={(updated) => {
            setEditing(false)
            setOrg(updated)
            toast(`Limits updated for ${updated.name}.`)
          }}
        />
      )}
    </>
  )
}

// ── Plans catalog (§7) ───────────────────────────────────────────────────────

const PLAN_ID_RE = /^[a-z][a-z0-9_-]*$/

const EMPTY_PLAN: PlanWrite = {
  display_name: '',
  max_seats: null,
  max_projects: null,
  max_api_tokens: null,
  max_mcp_tokens: null,
  allow_sso: false,
  allow_scim: false,
  allow_mcp: false,
  monthly_price_usd: 0,
  is_public: true,
}

function capText(cap: number | null): string {
  return cap === null ? 'unlimited' : String(cap)
}

function PlanDialog({ plan, onClose, onSaved }: { plan: PlanInfo | null; onClose: () => void; onSaved: (p: PlanInfo) => void }) {
  const isNew = plan === null
  const [id, setId] = useState(plan?.id ?? '')
  const [form, setForm] = useState<PlanWrite>(() => {
    if (!plan) return EMPTY_PLAN
    const { id: _ignored, ...rest } = plan
    void _ignored
    return rest
  })
  const [price, setPrice] = useState(plan ? (plan.monthly_price_usd / 100).toString() : '0')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const idInvalid = isNew && id !== '' && !PLAN_ID_RE.test(id)

  function cap(key: 'max_seats' | 'max_projects' | 'max_api_tokens' | 'max_mcp_tokens', label: string) {
    return (
      <label>
        {label}
        <input
          type="number"
          min={0}
          placeholder="unlimited"
          value={form[key] ?? ''}
          onChange={(e) => setForm({ ...form, [key]: numberOrNull(e.target.value) })}
        />
      </label>
    )
  }

  function flag(key: 'allow_sso' | 'allow_scim' | 'allow_mcp' | 'is_public', label: string) {
    return (
      <label className="toggle-field">
        <input type="checkbox" checked={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.checked })} />
        {label}
      </label>
    )
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onSaved(await api.adminSavePlan(id, { ...form, monthly_price_usd: Math.round(Number(price) * 100) }))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Can't reach the server.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open onClose={onClose}>
      <form onSubmit={submit}>
        <header>
          <h3>{isNew ? 'New plan' : `Edit ${plan.display_name}`}</h3>
          <p>
            {isNew
              ? 'The id is permanent. To sell it online, also map it to a Stripe Price in BUILDER_STRIPE_PRICE_IDS.'
              : 'Changes apply immediately to every organization on this plan. The Stripe price is not changed.'}
          </p>
        </header>
        <div>
          {error && (
            <div role="alert" data-variant="danger">
              {error}
            </div>
          )}
          <div className="field-grid">
            {isNew && (
              <label>
                Id
                <input required maxLength={40} value={id} onChange={(e) => setId(e.target.value.toLowerCase())} aria-invalid={idInvalid || undefined} placeholder="startup" />
              </label>
            )}
            <label>
              Display name
              <input required maxLength={100} value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
            </label>
            <label>
              Price (USD / month)
              <input type="number" min={0} step="0.01" value={price} onChange={(e) => setPrice(e.target.value)} />
            </label>
            {cap('max_seats', 'Seats')}
            {cap('max_projects', 'Projects')}
            {cap('max_api_tokens', 'API tokens per member')}
            {cap('max_mcp_tokens', 'MCP tokens')}
          </div>
          <div className="stack">
            {flag('allow_mcp', 'MCP access')}
            {flag('allow_sso', 'Single sign-on')}
            {flag('allow_scim', 'SCIM provisioning')}
            {flag('is_public', 'Shown to customers as an upgrade option')}
          </div>
        </div>
        <footer>
          <button type="button" className="outline" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" disabled={busy || !id || idInvalid || !form.display_name.trim()}>
            {busy ? 'Saving…' : 'Save plan'}
          </button>
        </footer>
      </form>
    </Modal>
  )
}

export function AdminPlans({ readOnly }: { readOnly: boolean }) {
  const { toast } = useUi()
  const [plans, setPlans] = useState<PlanInfo[] | null>(null)
  const [editing, setEditing] = useState<PlanInfo | 'new' | null>(null)
  useEffect(() => {
    api.adminPlans().then(setPlans).catch(() => setPlans([]))
  }, [])

  function saved(plan: PlanInfo) {
    setEditing(null)
    setPlans((list) => {
      const rest = (list ?? []).filter((p) => p.id !== plan.id)
      return [...rest, plan].sort((a, b) => a.monthly_price_usd - b.monthly_price_usd)
    })
    toast(`Saved the ${plan.display_name} plan.`)
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Plans</h1>
          <p>The catalog of plans and their caps. Empty caps mean unlimited.</p>
        </div>
        {!readOnly && <button onClick={() => setEditing('new')}>New plan</button>}
      </div>
      {plans === null ? (
        <p className="empty-state">Loading…</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Plan</th>
              <th>Price</th>
              <th>Seats</th>
              <th>Projects</th>
              <th>API tokens</th>
              <th>MCP tokens</th>
              <th>Features</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {plans.map((p) => (
              <tr key={p.id}>
                <td>
                  {p.display_name} <span className="muted small-text">{p.id}{p.is_public ? '' : ' · hidden'}</span>
                </td>
                <td>{p.monthly_price_usd ? `$${(p.monthly_price_usd / 100).toFixed(2)}` : 'Free'}</td>
                <td>{capText(p.max_seats)}</td>
                <td>{capText(p.max_projects)}</td>
                <td>{capText(p.max_api_tokens)}</td>
                <td>{p.allow_mcp ? capText(p.max_mcp_tokens) : <span className="muted">off</span>}</td>
                <td className="small-text">
                  {[p.allow_sso && 'SSO', p.allow_scim && 'SCIM'].filter(Boolean).join(', ') || <span className="muted">none</span>}
                </td>
                <td>
                  {!readOnly && (
                    <button className="outline small" onClick={() => setEditing(p)}>
                      Edit
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {editing && <PlanDialog plan={editing === 'new' ? null : editing} onClose={() => setEditing(null)} onSaved={saved} />}
    </>
  )
}

// ── Billing (§7: subscriptions, overdue, trials; Stripe stays the source) ─────

const BILLING_FILTERS: { id: string; label: string }[] = [
  { id: '', label: 'All' },
  { id: 'past_due', label: 'Overdue' },
  { id: 'trial', label: 'Trials' },
  { id: 'active', label: 'Active' },
  { id: 'canceled', label: 'Canceled' },
]

export function AdminBilling({ readOnly }: { readOnly: boolean }) {
  const { toast } = useUi()
  const [page, setPage] = useState<Page<AdminSubscription> | null>(null)
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)
  const [busy, setBusy] = useState(false)
  const [version, setVersion] = useState(0)
  useEffect(() => {
    const timer = setTimeout(
      () => api.adminSubscriptions({ status, q, limit: 25, offset }).then(setPage).catch(() => undefined),
      200,
    )
    return () => clearTimeout(timer)
  }, [status, q, offset, version])

  async function reconcile() {
    setBusy(true)
    try {
      const r = await api.adminReconcileBilling()
      toast(`Checked ${r.checked} Stripe subscription(s): ${r.changed} updated, ${r.failed} failed, ${r.trials_expired} trial(s) ended.`)
      setVersion((v) => v + 1)
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Can't reach the server.", 'danger')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <Header title="Billing">Subscriptions by status. Stripe is the source of truth for money; open it for invoices.</Header>
      <div className="table-toolbar">
        <span className="hstack">
          {BILLING_FILTERS.map((f) => (
            <button
              key={f.id}
              className={status === f.id ? 'small' : 'outline small'}
              onClick={() => {
                setOffset(0)
                setStatus(f.id)
              }}
            >
              {f.label}
            </button>
          ))}
        </span>
        <span className="hstack">
          <input type="search" placeholder="Search organization" value={q} onChange={(e) => { setOffset(0); setQ(e.target.value) }} />
          {!readOnly && (
            <button className="outline small" disabled={busy} onClick={reconcile} title="Re-read every Stripe subscription and end due trials">
              {busy ? 'Syncing…' : 'Sync with Stripe'}
            </button>
          )}
        </span>
      </div>
      {page && (
        <>
          <table>
            <thead>
              <tr>
                <th>Organization</th>
                <th>Plan</th>
                <th>Status</th>
                <th>Period end / trial end</th>
                <th>Stripe</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((s) => (
                <tr key={s.organization_id}>
                  <td>
                    <a href={`#/admin/organizations/${s.organization_id}`}>{s.organization_name}</a>{' '}
                    <span className="muted small-text">{s.organization_slug}</span>
                  </td>
                  <td>{s.plan_id}</td>
                  <td>
                    <span className={s.status === 'active' ? 'status-ok' : 'status-warn'}>{s.status}</span>
                  </td>
                  <td className="small-text">{s.status === 'trial' ? `trial ends ${when(s.trial_ends_at)}` : when(s.current_period_end)}</td>
                  <td className="small-text">
                    {s.stripe_subscription_id ? (
                      <a href={`https://dashboard.stripe.com/subscriptions/${s.stripe_subscription_id}`} target="_blank" rel="noreferrer">
                        open
                      </a>
                    ) : (
                      <span className="muted">not on Stripe</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager page={page} onPage={setOffset} />
        </>
      )}
    </>
  )
}

// ── Insights (§7: reporting over the audit log, no new tracking) ─────────────

function Sparkbars({ series, label }: { series: { day: string; count: number }[]; label: string }) {
  const max = Math.max(1, ...series.map((d) => d.count))
  const total = series.reduce((sum, d) => sum + d.count, 0)
  return (
    <div className="card stack">
      <div className="hstack justify-between">
        <strong>{label}</strong>
        <span className="muted small-text">{total} in 30 days</span>
      </div>
      <div className="sparkbars" role="img" aria-label={`${label}: ${total} in the last 30 days`}>
        {series.map((d) => (
          <span key={d.day} title={`${d.day}: ${d.count}`} style={{ height: `${(d.count / max) * 100}%` }} />
        ))}
      </div>
    </div>
  )
}

export function AdminInsightsPage() {
  const [data, setData] = useState<AdminInsights | null>(null)
  useEffect(() => {
    api.adminInsights().then(setData).catch(() => undefined)
  }, [])
  if (!data) return <p className="empty-state">Loading…</p>
  const tiles: [string, number][] = [
    ['Organizations', data.total_orgs],
    ['Active orgs (7 days)', data.active_orgs_7d],
    ['Projects', data.total_projects],
    ['MCP calls (24 h)', data.mcp_calls_24h],
    ['Denied by quota (7 days)', data.denied_by_quota_7d],
  ]
  return (
    <>
      <Header title="Insights">Counts from the audit log and account records. No per-user behaviour tracking.</Header>
      <div className="stat-grid">
        {tiles.map(([label, value]) => (
          <div key={label} className="card stat-card">
            <div className="stat-value">{value}</div>
            <div className="stat-label">{label}</div>
          </div>
        ))}
      </div>
      <div className="stat-grid">
        <Sparkbars series={data.signups_per_day} label="Sign-ups per day" />
        <Sparkbars series={data.orgs_per_day} label="Team organizations per day" />
      </div>
    </>
  )
}

// ── Audit log ────────────────────────────────────────────────────────────────

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export function AdminAudit() {
  const [page, setPage] = useState<Page<AuditEntry> | null>(null)
  const [action, setAction] = useState('')
  const [result, setResult] = useState('')
  const [via, setVia] = useState('')
  // #/admin/audit?organization_id=<uuid> opens the log filtered to one organization.
  const [orgId, setOrgId] = useState(() => new URLSearchParams(window.location.hash.split('?')[1] ?? '').get('organization_id') ?? '')
  const [offset, setOffset] = useState(0)
  const orgFilter = UUID_RE.test(orgId.trim()) ? orgId.trim() : undefined
  useEffect(() => {
    const timer = setTimeout(
      () =>
        api
          .adminAudit({ action, result, via, organization_id: orgFilter, limit: 50, offset })
          .then(setPage)
          .catch(() => undefined),
      200,
    )
    return () => clearTimeout(timer)
  }, [action, result, via, orgFilter, offset])
  return (
    <>
      <Header title="Audit log">An append-only record of sign-ins, changes and refused attempts.</Header>
      <div className="table-toolbar">
        <div className="hstack">
          <select aria-label="Event type" value={action} onChange={(e) => { setOffset(0); setAction(e.target.value) }}>
            <option value="">All events</option>
            <option value="account.">Accounts and sign-in</option>
            <option value="admin.">Administration</option>
            <option value="project.">Project changes</option>
            <option value="access.">Refused access</option>
            <option value="token.">API tokens</option>
            <option value="mcp.">MCP tool calls</option>
            <option value="org.">Organizations</option>
            <option value="plan.">Plans and checkout</option>
            <option value="billing.">Billing (Stripe)</option>
            <option value="quota.">Refused by plan limits</option>
            <option value="sso.">Single sign-on</option>
            <option value="scim.">SCIM provisioning</option>
          </select>
          <select aria-label="Outcome" value={result} onChange={(e) => { setOffset(0); setResult(e.target.value) }}>
            <option value="">Any outcome</option>
            <option value="ok">Succeeded</option>
            <option value="denied">Refused</option>
          </select>
          <select aria-label="Source" value={via} onChange={(e) => { setOffset(0); setVia(e.target.value) }}>
            <option value="">Any source</option>
            <option value="session">Browser session</option>
            <option value="api_token">API / MCP token</option>
            <option value="admin">Admin console</option>
            <option value="sso">SSO sign-in</option>
            <option value="scim">SCIM (identity provider)</option>
          </select>
          <input
            type="search"
            aria-label="Organization ID"
            placeholder="Organization ID"
            aria-invalid={orgId.trim() !== '' && !orgFilter}
            value={orgId}
            onChange={(e) => {
              setOffset(0)
              setOrgId(e.target.value)
            }}
          />
        </div>
      </div>
      {page && (
        <>
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>Who</th>
                <th>What</th>
                <th>Outcome</th>
                <th>From</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((e) => (
                <tr key={e.id}>
                  <td>{when(e.at)}</td>
                  <td>{auditActor(e)}</td>
                  <td>
                    {e.action}
                    {e.detail && <div className="muted small-text">{Object.entries(e.detail).map(([k, v]) => `${k}: ${String(v)}`).join(' · ')}</div>}
                  </td>
                  <td>
                    <span className={`badge ${e.result === 'ok' ? 'status-ok' : 'status-warn'}`}>{e.result}</span>
                  </td>
                  <td>{e.client_ip ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager page={page} onPage={setOffset} />
        </>
      )}
    </>
  )
}

// ── Settings (read-only: configuration is code) ──────────────────────────────

export function AdminSettings() {
  const [s, setS] = useState<PlatformSettings | null>(null)
  useEffect(() => {
    api.adminSettings().then(setS).catch(() => undefined)
  }, [])
  const rows: [string, string | number | boolean | undefined, string][] = [
    ['Environment', s?.environment, 'BUILDER_ENVIRONMENT'],
    ['Sign-up', s?.signup_mode, 'BUILDER_SIGNUP_MODE (open or closed)'],
    ['Access token lifetime (minutes)', s?.access_token_minutes, 'BUILDER_ACCESS_TOKEN_MINUTES'],
    ['Customer session (days)', s?.refresh_token_days, 'BUILDER_REFRESH_TOKEN_DAYS'],
    ['Admin session (hours)', s?.admin_refresh_token_hours, 'BUILDER_ADMIN_REFRESH_TOKEN_HOURS'],
    ['Failed sign-ins before lockout', s?.login_max_failures, 'BUILDER_LOGIN_MAX_FAILURES'],
    ['Lockout (minutes)', s?.lockout_minutes, 'BUILDER_LOCKOUT_MINUTES'],
    ['Trusts proxy headers', s ? String(s.trust_proxy_headers) : undefined, 'BUILDER_TRUST_PROXY_HEADERS'],
    ['API docs exposed', s ? String(s.docs_enabled) : undefined, 'BUILDER_ENABLE_DOCS'],
    ['Allowed web origins', s?.cors_origins.join(', '), 'BUILDER_CORS_ORIGINS'],
  ]
  return (
    <>
      <Header title="Settings">Read-only. Change these with environment variables and restart.</Header>
      <table>
        <tbody>
          {rows.map(([label, value, env]) => (
            <tr key={label}>
              <td>{label}</td>
              <td>
                <strong>{value === undefined ? '…' : String(value)}</strong>
              </td>
              <td className="muted small-text">
                <code>{env}</code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}
