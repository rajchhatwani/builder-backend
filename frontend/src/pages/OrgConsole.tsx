import { useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import { formatDeletionDate } from '../api/dates'
import { notifyOrgsChanged } from '../api/orgEvents'
import type {
  Organization,
  OrgAuditEntry,
  OrgInvitation,
  OrgInvitationCreated,
  OrgMember,
  OrgPlan,
  OrgRole,
  Page,
  Project,
} from '../api/types'
import { useUser } from '../components/AuthProvider'
import { link } from '../components/Sidebar'
import { useUi } from '../components/Ui'
import { AskAdmin } from '../components/AskAdmin'
import { OrgPlanPage } from './OrgPlanPage'
import { OrgPoliciesTab } from './OrgPoliciesTab'
import { OrgSsoTab } from './OrgSsoTab'

export type OrgTab = 'people' | 'invites' | 'projects' | 'plan' | 'audit' | 'sso' | 'policies'

const TABS: { id: OrgTab; label: string; path: string }[] = [
  { id: 'people', label: 'People', path: '' },
  { id: 'invites', label: 'Invites', path: '/invites' },
  { id: 'projects', label: 'Projects', path: '/projects' },
  { id: 'plan', label: 'Plan', path: '/plan' },
  { id: 'audit', label: 'Audit log', path: '/audit' },
  { id: 'sso', label: 'SSO & SCIM', path: '/sso' },
  { id: 'policies', label: 'Security', path: '/policies' },
]

const ROLE_LABEL: Record<OrgRole, string> = { owner: 'Owner', admin: 'Admin', member: 'Member' }

function message(err: unknown): string {
  return err instanceof ApiError ? err.message : "Can't reach the server."
}

function orgHref(slug: string, path = ''): string {
  return link(`/org/${encodeURIComponent(slug)}${path}`)
}

function timeLeft(expiresAt: string, now: number): string {
  const ms = new Date(expiresAt).getTime() - now
  if (ms <= 0) return 'expired'
  const days = Math.floor(ms / 86_400_000)
  if (days >= 1) return `${days} day${days === 1 ? '' : 's'} left`
  const hours = Math.max(1, Math.floor(ms / 3_600_000))
  return `${hours} hour${hours === 1 ? '' : 's'} left`
}

// ── People ───────────────────────────────────────────────────────────────────

interface PeopleTabProps {
  org: Organization
  members: OrgMember[]
  onChanged: () => void
}

function PeopleTab({ org, members, onChanged }: PeopleTabProps) {
  const me = useUser()
  const { confirm, toast } = useUi()
  const [error, setError] = useState<string | null>(null)
  const isOwner = org.my_role === 'owner'
  const canAdmin = isOwner || org.my_role === 'admin'

  async function run(action: () => Promise<unknown>, done: string) {
    setError(null)
    try {
      await action()
      toast(done)
      onChanged()
    } catch (err) {
      setError(message(err))
    }
  }

  async function remove(m: OrgMember) {
    const ok = await confirm({
      title: `Remove ${m.email} from ${org.name}?`,
      message: 'They lose access to the organization and to its projects.',
      confirmLabel: 'Remove',
      danger: true,
    })
    if (ok) await run(() => api.removeOrgMember(org.slug, m.user_id), 'Member removed.')
  }

  async function transfer(m: OrgMember) {
    const ok = await confirm({
      title: `Make ${m.email} the owner?`,
      message: 'They become an owner and you become an admin. Only an owner can undo this.',
      confirmLabel: 'Transfer ownership',
      danger: true,
    })
    if (ok) await run(() => api.transferOrgOwnership(org.slug, m.user_id), 'Ownership transferred.')
  }

  /** Admins manage members and admins; only owners touch other owners (§8: "except Owner"). */
  function roleChoices(m: OrgMember): OrgRole[] | null {
    if (m.user_id === me.id || !canAdmin) return null
    if (m.role === 'owner') return isOwner ? ['owner', 'admin', 'member'] : null
    return ['admin', 'member']
  }

  return (
    <div className="stack">
      {error && (
        <div role="alert" data-variant="danger">
          {error}
        </div>
      )}
      <table>
        <thead>
          <tr>
            <th>Member</th>
            <th>Role</th>
            <th>Status</th>
            <th>Last sign-in</th>
            <th>2FA</th>
            <th>Joined</th>
            {canAdmin && <th />}
          </tr>
        </thead>
        <tbody>
          {members.map((m) => {
            const choices = roleChoices(m)
            const removable = canAdmin && m.user_id !== me.id && (m.role !== 'owner' || isOwner)
            return (
              <tr key={m.user_id}>
                <td>
                  {m.name || m.email}
                  {m.user_id === me.id && <span className="muted"> (you)</span>}
                  {m.name && <div className="muted small-text">{m.email}</div>}
                </td>
                <td>
                  {choices ? (
                    <select
                      aria-label={`Role of ${m.email}`}
                      value={m.role}
                      onChange={(e) =>
                        run(() => api.setOrgMemberRole(org.slug, m.user_id, e.target.value as OrgRole), 'Role updated.')
                      }
                    >
                      {choices.map((r) => (
                        <option key={r} value={r}>
                          {ROLE_LABEL[r]}
                        </option>
                      ))}
                    </select>
                  ) : (
                    ROLE_LABEL[m.role]
                  )}
                </td>
                <td>
                  <span className={`badge ${m.status === 'suspended' ? 'badge-muted' : 'status-ok'}`}>
                    {m.status ?? 'active'}
                  </span>
                </td>
                <td className="small-text">
                  {m.last_login_at === undefined ? (
                    <span className="muted">—</span>
                  ) : m.last_login_at ? (
                    new Date(m.last_login_at).toLocaleDateString()
                  ) : (
                    <span className="muted">never</span>
                  )}
                </td>
                <td>
                  {m.mfa_enabled === undefined ? (
                    <span className="muted">—</span>
                  ) : (
                    <span className={`badge ${m.mfa_enabled ? 'status-ok' : 'badge-muted'}`}>{m.mfa_enabled ? 'on' : 'off'}</span>
                  )}
                </td>
                <td>{new Date(m.joined_at).toLocaleDateString()}</td>
                {canAdmin && (
                  <td className="row-actions">
                    {isOwner && m.role !== 'owner' && (
                      <button className="ghost small" onClick={() => transfer(m)}>
                        Make owner
                      </button>
                    )}
                    {removable && (
                      <button className="ghost small" data-variant="danger" onClick={() => remove(m)}>
                        Remove
                      </button>
                    )}
                  </td>
                )}
              </tr>
            )
          })}
        </tbody>
      </table>
      {canAdmin ? (
        <p className="muted small-text">
          Admins invite and remove people. Owners can also make someone else owner or delete the organization. If your
          identity provider maps groups to roles (SCIM), its next sync can change a role you set here.{' '}
          <a href={orgHref(org.slug, '/invites')}>Invite someone</a>
        </p>
      ) : (
        <AskAdmin members={members} what="invite, remove or change the role of people" />
      )}
    </div>
  )
}

// ── Invites ──────────────────────────────────────────────────────────────────

function InvitesTab({ org, members }: { org: Organization; members: OrgMember[] }) {
  const { confirm, toast } = useUi()
  const canAdmin = org.my_role === 'owner' || org.my_role === 'admin'
  const [invites, setInvites] = useState<OrgInvitation[] | null>(null)
  const [now, setNow] = useState(0)
  const [version, setVersion] = useState(0)
  const [showPast, setShowPast] = useState(false)
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<OrgRole>('member')
  const [fresh, setFresh] = useState<OrgInvitationCreated | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!canAdmin) return
    let cancelled = false
    api
      .orgInvitations(org.slug)
      .then((page) => {
        if (cancelled) return
        setInvites(page.items)
        setNow(Date.now())
      })
      .catch((err) => !cancelled && setError(message(err)))
    return () => {
      cancelled = true
    }
  }, [org.slug, canAdmin, version])

  if (!canAdmin) return <AskAdmin members={members} what="see and send invitations" />
  const isOwner = org.my_role === 'owner'

  async function invite(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const created = await api.createOrgInvitation(org.slug, email.trim(), role)
      setFresh(created)
      setEmail('')
      setVersion((v) => v + 1)
    } catch (err) {
      // A 402 (seat cap / past due) also opens the global upgrade prompt.
      setError(message(err))
    } finally {
      setBusy(false)
    }
  }

  async function revoke(inv: OrgInvitation) {
    const ok = await confirm({
      title: `Revoke the invitation for ${inv.email}?`,
      message: 'The link stops working. You can invite them again later.',
      confirmLabel: 'Revoke',
      danger: true,
    })
    if (!ok) return
    try {
      await api.revokeOrgInvitation(org.slug, inv.id)
      toast('Invitation revoked.')
      if (fresh?.id === inv.id) setFresh(null)
      setVersion((v) => v + 1)
    } catch (err) {
      setError(message(err))
    }
  }

  async function resend(inv: OrgInvitation) {
    try {
      const again = await api.resendOrgInvitation(org.slug, inv.id)
      setFresh(again)
      toast(again.emailed ? `Sent a new link to ${inv.email}.` : 'New link ready. The old one no longer works.')
      setVersion((v) => v + 1)
    } catch (err) {
      setError(message(err))
    }
  }

  const pending = invites?.filter((i) => i.status === 'pending') ?? []
  const past = invites?.filter((i) => i.status !== 'pending') ?? []

  return (
    <div className="stack">
      <form className="card stack" onSubmit={invite}>
        <h3>Invite someone</h3>
        {error && (
          <div role="alert" data-variant="danger">
            {error}
          </div>
        )}
        <div className="field-grid">
          <label>
            Email
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="teammate@example.com" />
          </label>
          <label>
            Role
            <select value={role} onChange={(e) => setRole(e.target.value as OrgRole)}>
              <option value="member">Member: works on the projects they're added to</option>
              <option value="admin">Admin: also manages people and the plan</option>
              {isOwner && <option value="owner">Owner: everything, incl. deleting the organization</option>}
            </select>
          </label>
          <div>
            <button type="submit" disabled={busy || !email.trim()}>
              {busy ? 'Inviting…' : 'Invite'}
            </button>
          </div>
        </div>
        <p className="muted small-text">Each pending invitation holds a seat until it's accepted, revoked or expires.</p>
      </form>

      {fresh && (
        <div role="alert" data-variant="success" className="stack">
          <strong>Send this link to {fresh.email}. It will not be shown again.</strong>
          <span className="small-text">
            {fresh.emailed
              ? `We emailed it to ${fresh.email}. Copy it too if you'd like to send it another way.`
              : `Email isn't set up on this platform, so send the link yourself. They sign in (or create an account) with ${fresh.email} and open it.`}
          </span>
          <code className="token-box">{fresh.invite_url}</code>
          <div>
            <button
              className="small"
              onClick={() => navigator.clipboard.writeText(fresh.invite_url).then(() => toast('Copied.'))}
            >
              Copy link
            </button>{' '}
            <button className="outline small" onClick={() => setFresh(null)}>
              I have sent it
            </button>
          </div>
        </div>
      )}

      <section className="stack">
        <div className="table-toolbar">
          <h3>Pending invitations</h3>
          {past.length > 0 && (
            <button className="ghost small" onClick={() => setShowPast((s) => !s)}>
              {showPast ? 'Hide past invitations' : `Show past invitations (${past.length})`}
            </button>
          )}
        </div>
        {invites === null ? (
          <p className="empty-state">Loading…</p>
        ) : pending.length === 0 && !showPast ? (
          <p className="muted">No pending invitations.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Email</th>
                <th>Role</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {[...pending, ...(showPast ? past : [])].map((inv) => (
                <tr key={inv.id}>
                  <td>{inv.email}</td>
                  <td>{ROLE_LABEL[inv.role]}</td>
                  <td>
                    {inv.status === 'pending' ? (
                      <span className="small-text">{timeLeft(inv.expires_at, now)}</span>
                    ) : (
                      <span className={`badge ${inv.status === 'accepted' ? 'status-ok' : 'badge-muted'}`}>{inv.status}</span>
                    )}
                  </td>
                  <td className="row-actions">
                    {(inv.status === 'pending' || inv.status === 'expired') && (
                      <button className="ghost small" onClick={() => resend(inv)}>
                        Resend
                      </button>
                    )}
                    {inv.status === 'pending' && (
                      <button className="ghost small" data-variant="danger" onClick={() => revoke(inv)}>
                        Revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted small-text">
          A lost link can't be shown again. Resend makes a new one (and the old one stops working).
        </p>
      </section>
    </div>
  )
}

// ── Projects ─────────────────────────────────────────────────────────────────

function ProjectsTab({ org }: { org: Organization }) {
  const { confirm, toast } = useUi()
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [mine, setMine] = useState<Set<string>>(new Set())
  const [ownedOrgs, setOwnedOrgs] = useState<Organization[]>([])
  const [error, setError] = useState<string | null>(null)
  const [newName, setNewName] = useState('')
  const [busy, setBusy] = useState(false)
  const [version, setVersion] = useState(0)
  const canAdmin = org.my_role === 'owner' || org.my_role === 'admin'
  const isOwner = org.my_role === 'owner'

  useEffect(() => {
    let cancelled = false
    Promise.all([api.orgProjects(org.slug), api.listProjects(200, 0), api.listOrgs()])
      .then(([orgPage, myPage, orgs]: [Page<Project>, Page<Project>, Page<Organization>]) => {
        if (cancelled) return
        setProjects(orgPage.items)
        setMine(new Set(myPage.items.map((p) => p.id)))
        setOwnedOrgs(orgs.items.filter((o) => o.my_role === 'owner' && o.id !== org.id && !o.deletion_scheduled_for))
      })
      .catch((err) => !cancelled && setError(message(err)))
    return () => {
      cancelled = true
    }
  }, [org.slug, org.id, version])

  async function create(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const project = await api.createProject({ name: newName.trim(), organization_id: org.id })
      window.location.hash = link(`/p/${project.id}/overview`)
    } catch (err) {
      setError(message(err)) // a 402 also opens the upgrade prompt
    } finally {
      setBusy(false)
    }
  }

  async function join(p: Project) {
    try {
      await api.joinOrgProject(org.slug, p.id, 'editor')
      toast(`You're now an editor of ${p.name}.`)
      setVersion((v) => v + 1)
    } catch (err) {
      setError(message(err))
    }
  }

  async function move(p: Project, to: Organization) {
    const ok = await confirm({
      title: `Move ${p.name} to ${to.name}?`,
      message: `It will count against ${to.name}'s plan. Everyone on the project must already be a member of ${to.name}.`,
      confirmLabel: 'Move project',
    })
    if (!ok) return
    try {
      await api.transferOrgProject(org.slug, p.id, to.slug)
      toast(`Moved ${p.name} to ${to.name}.`)
      setVersion((v) => v + 1)
    } catch (err) {
      setError(message(err))
    }
  }

  if (projects === null && !error) return <p className="empty-state">Loading…</p>

  return (
    <div className="stack">
      {error && (
        <div role="alert" data-variant="danger">
          {error}
        </div>
      )}
      <form className="hstack" onSubmit={create}>
        <input
          aria-label="New project name"
          placeholder={`New project in ${org.kind === 'personal' ? 'your workspace' : org.name}`}
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
        />
        <button type="submit" disabled={busy || !newName.trim()}>
          {busy ? 'Creating…' : 'New project'}
        </button>
      </form>
      {!projects || projects.length === 0 ? (
        <p className="muted">
          {canAdmin ? 'This organization has no projects yet.' : "You aren't on any of this organization's projects yet."}
        </p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Project</th>
              <th>Updated</th>
              <th>Your access</th>
              {(canAdmin || isOwner) && <th />}
            </tr>
          </thead>
          <tbody>
            {projects.map((p) => (
              <tr key={p.id}>
                <td>
                  {mine.has(p.id) ? <a href={link(`/p/${p.id}/overview`)}>{p.name}</a> : p.name}
                  {p.description && <div className="muted small-text">{p.description}</div>}
                </td>
                <td>{new Date(p.updated_at).toLocaleDateString()}</td>
                <td>
                  {mine.has(p.id) ? (
                    <span className="badge status-ok">Member</span>
                  ) : (
                    <span className="badge badge-muted">No access</span>
                  )}
                </td>
                {(canAdmin || isOwner) && (
                  <td className="row-actions">
                    {canAdmin && !mine.has(p.id) && (
                      <button className="ghost small" onClick={() => join(p)}>
                        Add me
                      </button>
                    )}
                    {isOwner && ownedOrgs.length > 0 && (
                      <select
                        aria-label={`Move ${p.name} to another organization`}
                        value=""
                        onChange={(e) => {
                          const to = ownedOrgs.find((o) => o.id === e.target.value)
                          if (to) move(p, to)
                        }}
                      >
                        <option value="">Move to…</option>
                        {ownedOrgs.map((o) => (
                          <option key={o.id} value={o.id}>
                            {o.kind === 'personal' ? 'Personal workspace' : o.name}
                          </option>
                        ))}
                      </select>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ── Audit log (§8: this org only, no request details) ───────────────────────

function AuditTab({ org, members }: { org: Organization; members: OrgMember[] }) {
  const canAdmin = org.my_role === 'owner' || org.my_role === 'admin'
  const [page, setPage] = useState<Page<OrgAuditEntry> | null>(null)
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!canAdmin) return
    let cancelled = false
    api
      .orgAudit(org.slug, 50, offset)
      .then((p) => !cancelled && setPage(p))
      .catch((err) => !cancelled && setError(message(err)))
    return () => {
      cancelled = true
    }
  }, [org.slug, offset, canAdmin])

  if (!canAdmin) return <AskAdmin members={members} what="read the audit log" />
  if (error) return <div role="alert" data-variant="danger">{error}</div>
  if (!page) return <p className="empty-state">Loading…</p>
  const to = Math.min(page.offset + page.limit, page.total)
  return (
    <div className="stack">
      <table>
        <thead>
          <tr>
            <th>When</th>
            <th>Who</th>
            <th>What</th>
            <th>Result</th>
          </tr>
        </thead>
        <tbody>
          {page.items.map((e) => (
            <tr key={e.id}>
              <td className="small-text">{new Date(e.at).toLocaleString()}</td>
              <td>{e.actor_email ?? <span className="muted">{e.via === 'scim' ? 'SCIM' : e.via}</span>}</td>
              <td>
                <code>{e.action}</code>
                {e.target_type && <span className="muted small-text"> {e.target_type}</span>}
              </td>
              <td>
                <span className={`badge ${e.result === 'ok' ? 'status-ok' : 'status-warn'}`}>{e.result}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="table-toolbar">
        <span className="muted small-text">
          {page.total === 0 ? 0 : page.offset + 1}–{to} of {page.total}
        </span>
        <span className="hstack">
          <button className="outline small" disabled={page.offset === 0} onClick={() => setOffset(Math.max(0, page.offset - page.limit))}>
            Previous
          </button>
          <button className="outline small" disabled={to >= page.total} onClick={() => setOffset(page.offset + page.limit)}>
            Next
          </button>
        </span>
      </div>
    </div>
  )
}

// ── Console shell ────────────────────────────────────────────────────────────

/** `#/org/<slug>[/invites|/projects|/plan]` — the customer org console (§8). */
export function OrgConsole({ slug, tab }: { slug: string; tab: OrgTab }) {
  const me = useUser()
  const { confirm, toast } = useUi()
  const [org, setOrg] = useState<Organization | null>(null)
  const [members, setMembers] = useState<OrgMember[]>([])
  const [plan, setPlan] = useState<OrgPlan | null>(null)
  const [missing, setMissing] = useState<string | null>(null)
  // The org requires two-factor and this session has none: only the org itself can be read.
  const [mfaBlocked, setMfaBlocked] = useState(false)
  const [version, setVersion] = useState(0)
  const [editingName, setEditingName] = useState(false)
  const [renaming, setRenaming] = useState('')

  useEffect(() => {
    let cancelled = false
    // The org first: a locked org (deletion pending) answers 423 on everything else, so don't ask.
    api
      .getOrg(slug)
      .then(async (o) => {
        if (o.deletion_scheduled_for) return { o, m: [] as OrgMember[], p: null, blocked: false }
        try {
          const [m, p] = await Promise.all([api.orgMembers(slug), api.orgPlan(slug).catch(() => null)])
          return { o, m: m.items, p, blocked: false }
        } catch (err) {
          if (err instanceof ApiError && err.code === 'org_mfa_required') return { o, m: [], p: null, blocked: true }
          throw err
        }
      })
      .then(({ o, m, p, blocked }) => {
        if (cancelled) return
        setOrg(o)
        setMembers(m)
        setPlan(p)
        setMfaBlocked(blocked)
        setMissing(null)
      })
      .catch((err) => {
        if (cancelled) return
        setOrg(null)
        setMissing(err instanceof ApiError && err.status === 404 ? 'not-found' : message(err))
      })
    return () => {
      cancelled = true
    }
  }, [slug, version])

  const reload = () => setVersion((v) => v + 1)

  if (missing) {
    return (
      <div className="card empty-hero">
        <h2>{missing === 'not-found' ? "We can't find this organization" : "Can't load this organization"}</h2>
        <p>{missing === 'not-found' ? "It may have been deleted, or you're not a member." : missing}</p>
        <a className="button" href="#/">
          Back to projects
        </a>
      </div>
    )
  }
  if (!org || org.slug !== slug) return <p className="empty-state">Loading…</p>

  const isOwner = org.my_role === 'owner'

  async function leave() {
    if (!org) return
    const ok = await confirm({
      title: `Leave ${org.name}?`,
      message: "You lose access to the organization. You'll need a new invitation to come back.",
      confirmLabel: 'Leave',
      danger: true,
    })
    if (!ok) return
    try {
      await api.removeOrgMember(org.slug, me.id)
      notifyOrgsChanged()
      toast(`You left ${org.name}.`)
      window.location.hash = link('/')
    } catch (err) {
      toast(message(err), 'danger')
    }
  }

  async function rename() {
    if (!org) return
    const name = renaming.trim()
    if (!name) return
    try {
      await api.renameOrg(org.slug, name)
      notifyOrgsChanged()
      setRenaming('')
      setEditingName(false)
      reload()
    } catch (err) {
      toast(message(err), 'danger')
    }
  }

  async function remove() {
    if (!org) return
    const ok = await confirm({
      title: `Delete ${org.name} and all its projects?`,
      message:
        'The organization is locked right away: nobody can open or change it or its projects. After a grace period it is deleted for good, together with all its projects. Until then an owner can cancel the deletion. Cancel any paid subscription first (Plan → Manage billing); the request is refused while one is active.',
      confirmLabel: 'Request deletion',
      danger: true,
    })
    if (!ok) return
    try {
      const updated = await api.deleteOrg(org.slug)
      notifyOrgsChanged()
      toast(`${org.name} will be deleted on ${formatDeletionDate(updated.deletion_scheduled_for)}.`)
      reload()
    } catch (err) {
      toast(message(err), 'danger')
    }
  }

  async function cancelDeletion() {
    if (!org) return
    try {
      await api.cancelOrgDeletion(org.slug)
      notifyOrgsChanged()
      toast(`Deletion cancelled. ${org.name} is unlocked.`)
      reload()
    } catch (err) {
      toast(message(err), 'danger')
    }
  }

  if (org.deletion_scheduled_for) {
    return (
      <>
        <div className="page-header">
          <div>
            <h1>{org.name}</h1>
            <p>
              you are {ROLE_LABEL[org.my_role].toLowerCase()} · <span className="status-warn">locked</span>
            </p>
          </div>
        </div>
        <div role="alert" data-variant="danger" className="stack">
          <strong>Scheduled for deletion on {formatDeletionDate(org.deletion_scheduled_for)}.</strong>
          <span>
            On that date the organization is deleted together with all its projects. Until then it's locked: its
            people, projects, plan and audit log can't be opened or changed.
          </span>
          {isOwner ? (
            <div>
              <button onClick={cancelDeletion}>Cancel deletion</button>
            </div>
          ) : (
            <span className="small-text">Only an owner can cancel the deletion. Ask one of them if this is a mistake.</span>
          )}
        </div>
      </>
    )
  }

  if (mfaBlocked) {
    return (
      <>
        <div className="page-header">
          <div>
            <h1>{org.name}</h1>
            <p>you are {ROLE_LABEL[org.my_role].toLowerCase()}</p>
          </div>
          {org.kind === 'team' && (
            <div className="hstack">
              <button className="outline small" onClick={leave}>
                Leave
              </button>
            </div>
          )}
        </div>
        <div role="alert" data-variant="warning" className="stack">
          <strong>{org.name} requires two-factor authentication.</strong>
          <span>
            {me.mfa_enabled
              ? 'This session was started without your code. Sign out and sign in again with it.'
              : 'Turn on two-factor in your account, then sign in again with your code.'}
          </span>
          <div>
            <a className="button small" href="#/account">
              Open your account
            </a>
          </div>
        </div>
      </>
    )
  }

  const status = plan?.subscription.status
  // SSO is for team orgs only (personal orgs answer 409 sso_not_for_personal_orgs).
  const tabs = TABS.filter((t) => t.id !== 'sso' || org.kind === 'team')

  return (
    <>
      <div className="page-header">
        <div>
          {editingName ? (
            <form
              className="hstack"
              onSubmit={(e) => {
                e.preventDefault()
                rename()
              }}
            >
              <input aria-label="Organization name" autoFocus maxLength={100} value={renaming} onChange={(e) => setRenaming(e.target.value)} />
              <button type="submit" className="small" disabled={!renaming.trim()}>
                Save
              </button>
              <button type="button" className="outline small" onClick={() => setEditingName(false)}>
                Cancel
              </button>
            </form>
          ) : (
            <h1>
              {org.kind === 'personal' ? 'Personal workspace' : org.name}
              {org.kind === 'team' && org.my_role !== 'member' && (
                <button
                  className="ghost small"
                  onClick={() => {
                    setRenaming(org.name)
                    setEditingName(true)
                  }}
                >
                  Rename
                </button>
              )}
            </h1>
          )}
          <p>
            {org.member_count} member{org.member_count === 1 ? '' : 's'} · you are {ROLE_LABEL[org.my_role].toLowerCase()}
            {plan && (
              <>
                {' '}
                · <a href={orgHref(org.slug, '/plan')}>{plan.plan.display_name} plan</a>{' '}
                <span className={status === 'active' ? 'status-ok' : 'status-warn'}>{status}</span>
              </>
            )}
          </p>
        </div>
        {org.kind === 'team' && (
          <div className="hstack">
            <button className="outline small" onClick={leave}>
              Leave
            </button>
            {isOwner && (
              <button className="outline small" data-variant="danger" onClick={remove}>
                Delete organization
              </button>
            )}
          </div>
        )}
      </div>

      {org.kind === 'team' && plan?.plan.id === 'free' && org.my_role !== 'member' && tab !== 'plan' && (
        <div role="alert" data-variant="warning">
          {org.name} is on the Free plan
          {plan.usage.seats_cap !== null &&
            ` (${plan.usage.seats_cap} seat${plan.usage.seats_cap === 1 ? '' : 's'})`}
          , so inviting people needs an upgrade first. <a href={orgHref(org.slug, '/plan')}>See plans</a>.
        </div>
      )}

      {status === 'past_due' && tab !== 'plan' && (
        <div role="alert" data-variant="danger">
          The last payment failed, so new members and projects are paused.{' '}
          <a href={orgHref(org.slug, '/plan')}>See the plan page</a>.
        </div>
      )}

      <div className="tab-bar" role="tablist">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            className="tab-btn"
            aria-selected={tab === t.id}
            onClick={() => (window.location.hash = orgHref(org.slug, t.path))}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'people' && <PeopleTab org={org} members={members} onChanged={reload} />}
      {tab === 'invites' && <InvitesTab org={org} members={members} />}
      {tab === 'projects' && <ProjectsTab org={org} />}
      {tab === 'plan' && <OrgPlanPage slug={org.slug} embedded />}
      {tab === 'audit' && <AuditTab org={org} members={members} />}
      {tab === 'sso' && org.kind === 'team' && <OrgSsoTab org={org} members={members} />}
      {tab === 'policies' && <OrgPoliciesTab org={org} members={members} onChanged={reload} />}
    </>
  )
}
