import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../../api/client'
import type {
  AdminOrg,
  AdminProject,
  AdminStats,
  AdminUser,
  ApiTokenInfo,
  AuditEntry,
  Page,
  PlatformRole,
  PlatformSettings,
  UserAccount,
} from '../../api/types'
import { Modal } from '../../components/Modal'
import { useUi } from '../../components/Ui'

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
                <th>Overrides</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {page.items.map((o) => (
                <tr key={o.id}>
                  <td>
                    {o.name} <span className="muted small-text">{o.slug}{o.kind === 'personal' ? ' · personal' : ''}</span>
                  </td>
                  <td>
                    {o.plan_id} <span className="muted small-text">{o.status}</span>
                  </td>
                  <td>{o.member_count}</td>
                  <td>{o.project_count}</td>
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
    </>
  )
}

// ── Audit log ────────────────────────────────────────────────────────────────

export function AdminAudit() {
  const [page, setPage] = useState<Page<AuditEntry> | null>(null)
  const [action, setAction] = useState('')
  const [result, setResult] = useState('')
  const [via, setVia] = useState('')
  const [offset, setOffset] = useState(0)
  useEffect(() => {
    const timer = setTimeout(
      () =>
        api
          .adminAudit({ action, result, via, limit: 50, offset })
          .then(setPage)
          .catch(() => undefined),
      200,
    )
    return () => clearTimeout(timer)
  }, [action, result, via, offset])
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
          </select>
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
                  <td>{e.actor_email ?? <span className="muted">system</span>}</td>
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
