import { useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import type { Organization, OrgMember, OrgPolicies, OrgPoliciesUpdate } from '../api/types'
import { AskAdmin } from '../components/AskAdmin'
import { useUi } from '../components/Ui'

function message(err: unknown): string {
  if (!(err instanceof ApiError)) return "Can't reach the server."
  if (err.code === 'enable_mfa_first') {
    return 'Your own session must use two-factor before you can require it, so nobody gets locked out. Turn on two-factor in your account, sign in again with your code, then come back.'
  }
  return err.message
}

function hoursText(hours: number): string {
  return hours % 24 === 0 ? `${hours / 24} day${hours === 24 ? '' : 's'}` : `${hours} hour${hours === 1 ? '' : 's'}`
}

/** `#/org/<slug>/policies` — security policies (§8): require two-factor, session length. */
export function OrgPoliciesTab({ org, members, onChanged }: { org: Organization; members: OrgMember[]; onChanged: () => void }) {
  const { confirm, toast } = useUi()
  const canAdmin = org.my_role === 'owner' || org.my_role === 'admin'
  const [policies, setPolicies] = useState<OrgPolicies | null>(null)
  const [requireMfa, setRequireMfa] = useState(false)
  const [allowSupport, setAllowSupport] = useState(true)
  const [exporting, setExporting] = useState(false)
  const [customTtl, setCustomTtl] = useState(false)
  const [ttl, setTtl] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  function adopt(p: OrgPolicies) {
    setPolicies(p)
    setRequireMfa(p.require_mfa)
    setAllowSupport(p.allow_impersonation)
    setCustomTtl(p.session_ttl_hours !== null)
    setTtl(p.session_ttl_hours === null ? '' : String(p.session_ttl_hours))
  }

  useEffect(() => {
    if (!canAdmin) return
    let cancelled = false
    api
      .orgPolicies(org.slug)
      .then((p) => !cancelled && adopt(p))
      .catch((err) => !cancelled && setError(message(err)))
    return () => {
      cancelled = true
    }
  }, [org.slug, canAdmin])

  if (!canAdmin) {
    return (
      <div className="stack">
        <p>
          Two-factor required: <strong>{org.require_mfa ? 'yes' : 'no'}</strong> · Session length:{' '}
          <strong>{org.session_ttl_hours ? hoursText(org.session_ttl_hours) : 'platform default'}</strong>
        </p>
        <AskAdmin members={members} what="change security policies" />
      </div>
    )
  }
  if (!policies) return error ? <div role="alert" data-variant="danger">{error}</div> : <p className="empty-state">Loading…</p>

  const ttlValue = customTtl ? Number(ttl) : null
  const ttlValid = !customTtl || (Number.isInteger(ttlValue) && ttlValue! >= 1 && ttlValue! <= 720)
  const changes: OrgPoliciesUpdate = {}
  if (requireMfa !== policies.require_mfa) changes.require_mfa = requireMfa
  if (ttlValue !== policies.session_ttl_hours) changes.session_ttl_hours = ttlValue
  if (allowSupport !== policies.allow_impersonation) changes.allow_impersonation = allowSupport
  const dirty = Object.keys(changes).length > 0

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!dirty || !ttlValid || !policies) return
    if (changes.require_mfa && policies.members_without_mfa > 0) {
      const n = policies.members_without_mfa
      const ok = await confirm({
        title: 'Require two-factor authentication?',
        message: `${n} member${n === 1 ? " hasn't" : "s haven't"} turned on two-factor. They will be blocked from ${org.name}'s projects until they do. Members who have it on must sign in again with their code.`,
        confirmLabel: 'Require two-factor',
        danger: true,
      })
      if (!ok) return
    }
    if (changes.allow_impersonation === false) {
      const ok = await confirm({
        title: 'Stop platform support from viewing as your members?',
        message:
          'Support sessions that are running right now end immediately, and support will not be able to see what your members see when they help with a problem.',
        confirmLabel: 'Turn off',
        danger: true,
      })
      if (!ok) return
    }
    setBusy(true)
    setError(null)
    try {
      adopt(await api.updateOrgPolicies(org.slug, changes))
      toast('Security policies saved.')
      onChanged()
    } catch (err) {
      setError(message(err))
    } finally {
      setBusy(false)
    }
  }

  async function exportData() {
    setExporting(true)
    try {
      const { blob, filename } = await api.exportOrg(org.slug)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      URL.revokeObjectURL(url)
      toast('Export downloaded.')
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Can't reach the server.", 'danger')
    } finally {
      setExporting(false)
    }
  }

  return (
    <form className="stack" onSubmit={save}>
      {error && (
        <div role="alert" data-variant="danger" className="stack">
          <span>{error}</span>
          {error.includes('Turn on two-factor') && (
            <span>
              <a href="#/account">Open your account</a>
            </span>
          )}
        </div>
      )}

      <section className="card stack">
        <h3>Two-factor authentication</h3>
        <label className="check-row">
          <input type="checkbox" checked={requireMfa} onChange={(e) => setRequireMfa(e.target.checked)} />
          <span>
            <strong>Require two-factor for every member</strong>{' '}
            <span className="muted small-text">
              Sessions without a second factor can't open this organization or its projects. SSO sign-ins count, because
              the identity provider handles it.
            </span>
          </span>
        </label>
        <p className="small-text">
          {policies.members_without_mfa === 0
            ? 'Every member has two-factor turned on.'
            : `${policies.members_without_mfa} member${policies.members_without_mfa === 1 ? " doesn't" : "s don't"} have two-factor turned on yet${requireMfa ? ' and will be blocked until they do' : ''}.`}
        </p>
      </section>

      <section className="card stack">
        <h3>Session length</h3>
        <p className="muted small-text">
          How long members stay signed in, counted from sign-in, however active they are. With several organizations
          the shortest limit wins.
        </p>
        <label className="check-row">
          <input type="radio" name="ttl" checked={!customTtl} onChange={() => setCustomTtl(false)} />
          <span>Platform default ({hoursText(policies.default_session_hours)})</span>
        </label>
        <label className="check-row">
          <input
            type="radio"
            name="ttl"
            checked={customTtl}
            onChange={() => {
              setCustomTtl(true)
              if (!ttl) setTtl('24')
            }}
          />
          <span>Custom</span>
        </label>
        {customTtl && (
          <label>
            Hours (1–720)
            <input type="number" min={1} max={720} step={1} required value={ttl} onChange={(e) => setTtl(e.target.value)} />
            {ttlValid && ttlValue && <small className="muted">{hoursText(ttlValue)}</small>}
          </label>
        )}
      </section>

      <section className="card stack">
        <h3>Platform support access</h3>
        <label className="check-row">
          <input type="checkbox" checked={allowSupport} onChange={(e) => setAllowSupport(e.target.checked)} />
          <span>
            <strong>Allow platform support to view as a member when helping with a problem</strong>{' '}
            <span className="muted small-text">
              A support session lasts ten minutes, starts read-only, needs a written reason, and every request is in
              your audit log. Support can never see credentials, tokens, billing or export your data. Turn this off and
              support cannot start a session at all.
            </span>
          </span>
        </label>
      </section>

      <div>
        <button type="submit" disabled={busy || !dirty || !ttlValid}>
          {busy ? 'Saving…' : 'Save policies'}
        </button>
      </div>

      {org.my_role === 'owner' && (
        <section className="card stack">
          <h3>Export your data</h3>
          <p className="muted small-text">
            Download everything held about {org.name} as one JSON file: people, projects with their specifications,
            policies, plan and audit log. It never contains passwords, tokens, or the credentials stored for your projects.
            Available even while the organization is scheduled for deletion.
          </p>
          <div>
            <button type="button" className="outline" disabled={exporting} onClick={exportData}>
              {exporting ? 'Preparing…' : 'Download export'}
            </button>
          </div>
        </section>
      )}
    </form>
  )
}
