import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Organization, ScimConfig, ScimRole } from '../api/types'
import { Copyable } from '../components/Copyable'
import { link } from '../components/Sidebar'
import { useUi } from '../components/Ui'

const ERRORS: Record<string, string> = {
  scim_not_for_personal_orgs: 'SCIM is only for team organizations.',
  scim_not_configured: 'Generate a token first.',
  session_required: 'SCIM settings can only be changed from a signed-in browser session.',
  scim_not_in_plan: "SCIM provisioning isn't included in this organization's plan.",
}

/** Owner-only rule for group mappings (§2.2: admins can't make owners). */
const OWNER_ONLY =
  'Only an owner can map a group to Owner, or change mappings that already include Owner.'

function message(err: unknown): string {
  if (!(err instanceof ApiError)) return "Can't reach the server."
  if (err.code === 'org_role_required') {
    const needed = (err.details[0] as { needed_role?: string } | undefined)?.needed_role
    if (needed === 'owner') return OWNER_ONLY
  }
  if (err.status === 422) return `${err.message}. Check the group names and roles.`
  return ERRORS[err.code] ?? err.message
}

function when(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : 'never'
}

const ROLE_LABEL: Record<ScimRole, string> = { owner: 'Owner', admin: 'Admin', member: 'Member' }
const MAX_MAPPINGS = 100

interface MappingRow {
  key: number
  group: string
  role: ScimRole
}

let nextKey = 0
function rowsFrom(groupRoles: Record<string, ScimRole>): MappingRow[] {
  return Object.entries(groupRoles).map(([group, role]) => ({ key: nextKey++, group, role }))
}

/** The token, shown once: copy it, tick "I saved it", and it's gone from memory. */
function TokenOnce({ token, onDone }: { token: string; onDone: () => void }) {
  const [saved, setSaved] = useState(false)
  return (
    <div className="stack">
      <div role="alert" data-variant="warning">
        Copy this token into your identity provider now. It will not be shown again; if you lose it, rotate the token.
      </div>
      <Copyable label="Token" value={token} />
      <label className="check-row">
        <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} />
        <span>I saved the token in my identity provider</span>
      </label>
      <div>
        <button type="button" disabled={!saved} onClick={onDone}>
          Done
        </button>
      </div>
    </div>
  )
}

function MappingEditor({
  slug,
  config,
  isOwner,
  onSaved,
}: {
  slug: string
  config: ScimConfig
  isOwner: boolean
  onSaved: (c: ScimConfig) => void
}) {
  const { toast } = useUi()
  const [rows, setRows] = useState<MappingRow[]>(() => rowsFrom(config.group_roles))
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // Admins can't touch a dictionary that maps any group to Owner.
  const lockedForMe = !isOwner && Object.values(config.group_roles).includes('owner')
  const roles: ScimRole[] = isOwner ? ['owner', 'admin', 'member'] : ['admin', 'member']
  const names = rows.map((r) => r.group.trim().toLowerCase()).filter(Boolean)
  const duplicate = names.find((n, i) => names.indexOf(n) !== i)
  const datalistId = `scim-groups-${slug}`

  function update(key: number, patch: Partial<MappingRow>) {
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)))
  }

  async function save() {
    setBusy(true)
    setError(null)
    const group_roles: Record<string, ScimRole> = {}
    for (const r of rows) {
      const name = r.group.trim().toLowerCase()
      if (name) group_roles[name] = r.role
    }
    try {
      const saved = await api.updateScim(slug, { group_roles })
      setRows(rowsFrom(saved.group_roles))
      toast('Group mappings saved.')
      onSaved(saved)
    } catch (err) {
      setError(message(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card stack">
      <h3>Groups and roles</h3>
      <p className="muted small-text">
        People in mapped groups get the highest mapped role; everyone else provisioned by SCIM is a Member. With no
        mappings, SCIM doesn't change roles.
      </p>
      {error && (
        <div role="alert" data-variant="danger">
          {error}
        </div>
      )}
      {lockedForMe && (
        <div role="alert" data-variant="warning">
          {OWNER_ONLY}
        </div>
      )}

      {config.groups.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Group from your IdP</th>
              <th>Members</th>
              <th>Role</th>
            </tr>
          </thead>
          <tbody>
            {config.groups.map((g) => (
              <tr key={g.display_name}>
                <td>{g.display_name}</td>
                <td>{g.members}</td>
                <td>{g.mapped_role ? ROLE_LABEL[g.mapped_role as ScimRole] ?? g.mapped_role : <span className="muted">not mapped</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {rows.length === 0 && <p className="small-text">No mappings yet.</p>}
      <datalist id={datalistId}>
        {config.groups.map((g) => (
          <option key={g.display_name} value={g.display_name} />
        ))}
      </datalist>
      {rows.map((r) => (
        <div key={r.key} className="hstack">
          <input
            aria-label="Group name"
            placeholder="Group name, e.g. Builder Admins"
            list={datalistId}
            maxLength={255}
            disabled={lockedForMe}
            value={r.group}
            onChange={(e) => update(r.key, { group: e.target.value })}
          />
          <select
            aria-label={`Role for ${r.group || 'this group'}`}
            disabled={lockedForMe}
            value={r.role}
            onChange={(e) => update(r.key, { role: e.target.value as ScimRole })}
          >
            {(roles.includes(r.role) ? roles : [r.role, ...roles]).map((role) => (
              <option key={role} value={role}>
                {ROLE_LABEL[role]}
              </option>
            ))}
          </select>
          {!lockedForMe && (
            <button
              type="button"
              className="ghost small"
              data-variant="danger"
              onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}
            >
              Remove
            </button>
          )}
        </div>
      ))}
      {duplicate && (
        <p className="small-text status-warn">
          "{duplicate}" is listed twice. Group names are compared without case.
        </p>
      )}
      {!lockedForMe && (
        <div className="hstack">
          <button
            type="button"
            className="outline small"
            disabled={rows.length >= MAX_MAPPINGS}
            onClick={() => setRows((rs) => [...rs, { key: nextKey++, group: '', role: 'member' }])}
          >
            Add mapping
          </button>
          <button type="button" className="small" disabled={busy || !!duplicate} onClick={save}>
            {busy ? 'Saving…' : 'Save mappings'}
          </button>
        </div>
      )}
    </section>
  )
}

/**
 * The SCIM part of `#/org/<slug>/sso` ("SSO & SCIM", §8, §12.E.5). Shown to org admins
 * of team orgs only; the parent tab handles members and personal orgs.
 */
export function OrgScimSection({
  org,
  verifiedDomains,
  ssoActive,
}: {
  org: Organization
  verifiedDomains: number
  ssoActive: boolean
}) {
  const { confirm, toast } = useUi()
  const isOwner = org.my_role === 'owner'
  const [config, setConfig] = useState<ScimConfig | null>(null)
  // The fresh token lives only here, only until "Done".
  const [token, setToken] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    api
      .scimConfig(org.slug)
      .then(setConfig)
      .catch((err) => setError(message(err)))
  }, [org.slug])

  useEffect(load, [load])

  if (!config) {
    return (
      <section className="card stack">
        <h3>SCIM provisioning</h3>
        {error ? (
          <div role="alert" data-variant="danger">
            {error}
          </div>
        ) : (
          <p className="empty-state">Loading…</p>
        )}
      </section>
    )
  }

  const planHref = link(`/org/${encodeURIComponent(org.slug)}/plan`)
  // After an operator rotation nobody knows the token, so turning SCIM on is pointless.
  const tokenUnknown = config.configured && !config.token_hint

  async function act(action: () => Promise<unknown>, done?: string) {
    setBusy(true)
    setError(null)
    try {
      await action()
      if (done) toast(done)
    } catch (err) {
      setError(message(err)) // 402 scim_not_in_plan also opens the upgrade prompt
    } finally {
      setBusy(false)
    }
  }

  async function issue() {
    if (config?.configured && config.token_hint) {
      const ok = await confirm({
        title: 'Rotate the SCIM token?',
        message: 'The current token stops working immediately. Update your IdP right away.',
        confirmLabel: 'Rotate token',
        danger: true,
      })
      if (!ok) return
    }
    await act(async () => {
      const { token: raw, ...rest } = await api.issueScimToken(org.slug)
      setConfig(rest)
      setToken(raw)
    })
  }

  async function toggle(on: boolean) {
    if (!on) {
      const ok = await confirm({
        title: 'Turn off SCIM?',
        message: "Your identity provider's sync requests are refused until you turn it back on. Nobody is removed.",
        confirmLabel: 'Turn off',
        danger: true,
      })
      if (!ok) return
    }
    await act(async () => setConfig(await api.updateScim(org.slug, { active: on })), on ? 'SCIM is on.' : 'SCIM is off.')
  }

  async function remove() {
    const ok = await confirm({
      title: 'Remove SCIM?',
      message: "People stay in the organization; the IdP can't sync any more. The token and the synced user and group records are deleted.",
      confirmLabel: 'Remove SCIM',
      danger: true,
    })
    if (!ok) return
    await act(async () => {
      await api.deleteScim(org.slug)
      setToken(null)
      load()
    }, 'SCIM removed.')
  }

  return (
    <div className="stack">
      <h2>SCIM provisioning</h2>
      {error && (
        <div role="alert" data-variant="danger">
          {error}
        </div>
      )}
      {!config.allowed_by_plan && (
        <div role="alert" data-variant="warning">
          SCIM provisioning isn't included in {org.name}'s plan. <a href={planHref}>See plans</a> to upgrade.
        </div>
      )}

      <section className="card stack">
        <div className="table-toolbar">
          <h3>Status</h3>
          {config.configured ? (
            <span className={`badge ${config.active ? 'status-ok' : 'badge-muted'}`}>{config.active ? 'on' : 'off'}</span>
          ) : (
            <span className="badge badge-muted">not set up</span>
          )}
        </div>
        {config.configured && (
          <p className="small-text">
            {config.last_sync_at ? `Last sync ${when(config.last_sync_at)}` : "The IdP hasn't connected yet."} ·{' '}
            {config.active_users} active user{config.active_users === 1 ? '' : 's'} · {config.deactivated_users}{' '}
            deactivated
            {config.token_created_at && <> · token created {when(config.token_created_at)}</>}
            {config.token_hint && (
              <>
                {' '}
                (<code>bb_scim_…{config.token_hint}</code>)
              </>
            )}
          </p>
        )}
        {tokenUnknown && (
          <div role="alert" data-variant="warning">
            Builder support replaced this organization's SCIM token, and nobody knows the new one, so SCIM is off. Generate
            a new token and paste it into your identity provider; SCIM switches back on with it.
          </div>
        )}

        {token && <TokenOnce token={token} onDone={() => setToken(null)} />}

        <div className="hstack">
          {!config.configured || tokenUnknown ? (
            <button type="button" disabled={busy || !config.allowed_by_plan} onClick={issue}>
              {config.configured ? 'Generate a new token' : 'Generate token'}
            </button>
          ) : (
            <button type="button" className="outline" disabled={busy} onClick={issue}>
              Rotate token
            </button>
          )}
          {config.configured &&
            !tokenUnknown &&
            (config.active ? (
              <button type="button" className="outline" data-variant="danger" disabled={busy} onClick={() => toggle(false)}>
                Turn off SCIM
              </button>
            ) : (
              <button type="button" disabled={busy || !config.allowed_by_plan} onClick={() => toggle(true)}>
                Turn on SCIM
              </button>
            ))}
          {config.configured && (
            <button type="button" className="ghost" data-variant="danger" disabled={busy} onClick={remove}>
              Remove SCIM
            </button>
          )}
        </div>
      </section>

      <section className="card stack">
        <h3>Connect your identity provider</h3>
        <ol className="stack small-text">
          <li>
            {verifiedDomains > 0 ? (
              <span className="status-ok">Done:</span>
            ) : (
              <span className="status-warn">To do:</span>
            )}{' '}
            verify a domain in{' '}
            <a
              href="#sso-domains"
              onClick={(e) => {
                e.preventDefault()
                document.getElementById('sso-domains')?.scrollIntoView({ behavior: 'smooth' })
              }}
            >
              Domains
            </a>{' '}
            above. SCIM can only provision people whose addresses are on your verified domains.
          </li>
          <li>
            {ssoActive ? <span className="status-ok">Done:</span> : <span className="status-warn">To do:</span>} set up
            single sign-on above. Accounts created by SCIM have no password; they sign in through SSO.
          </li>
          <li>
            Generate a token, then paste the base URL and the token into Okta, Entra ID, JumpCloud or Google Workspace
            (SCIM 2.0, bearer token / "HTTP header" authentication).
          </li>
          <li>Optionally, map your IdP's groups to roles below.</li>
        </ol>
        <Copyable label="Base URL" value={config.base_url} />
        <Copyable label="Users URL" value={config.users_url} />
      </section>

      {config.configured && (
        <MappingEditor
          key={JSON.stringify(config.group_roles)}
          slug={org.slug}
          config={config}
          isOwner={isOwner}
          onSaved={setConfig}
        />
      )}
    </div>
  )
}
