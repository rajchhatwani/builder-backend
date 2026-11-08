import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type {
  AdminOrg,
  PlatformRole,
  PreviewLimitKey,
  PreviewLimits,
  PreviewLimitValues,
  PreviewOrgLimitsRow,
  PreviewUsage,
} from '../../api/types'
import { useUi } from '../../components/Ui'
import { issuesFromDetail, type PathErrors } from '../../forms'
import { Field, LoadFailed } from '../../shell/behavior/ui'

export const LIMIT_FIELDS: { key: PreviewLimitKey; label: string; unit: string }[] = [
  { key: 'max_live_per_user', label: 'Live previews per person', unit: 'previews' },
  { key: 'sleep_after_minutes', label: 'Sleep after idle', unit: 'minutes' },
  { key: 'delete_after_days', label: 'Delete after', unit: 'days' },
  { key: 'cpus', label: 'CPU per preview', unit: 'cores' },
  { key: 'memory_mb', label: 'Memory per preview', unit: 'MB' },
  { key: 'db_mb', label: 'Database size per preview', unit: 'MB' },
  { key: 'rate_per_minute', label: 'Requests per minute', unit: 'requests' },
]
type Draft = Record<PreviewLimitKey, string>

const emptyDraft = (): Draft => Object.fromEntries(LIMIT_FIELDS.map((f) => [f.key, ''])) as Draft
const draftOf = (v: Partial<PreviewLimitValues>): Draft => {
  const d = emptyDraft()
  for (const f of LIMIT_FIELDS) if (v[f.key] !== undefined) d[f.key] = String(v[f.key])
  return d
}

/** Only the keys that were filled in (and, for the defaults form, changed). Returns an error message for non-numbers. */
export function numbersFromDraft(d: Draft, base?: Partial<PreviewLimitValues>): { ok: Partial<PreviewLimitValues>; bad: Partial<Record<PreviewLimitKey, string>> } {
  const ok: Partial<PreviewLimitValues> = {}
  const bad: Partial<Record<PreviewLimitKey, string>> = {}
  for (const f of LIMIT_FIELDS) {
    const t = d[f.key].trim()
    if (t === '') continue
    const n = Number(t)
    if (!Number.isFinite(n)) bad[f.key] = 'Enter a number.'
    else if (base === undefined || base[f.key] !== n) ok[f.key] = n
  }
  return { ok, bad }
}

const msgs = (ext: PathErrors, prefix: string, key: PreviewLimitKey) => ext[`${prefix}.${key}`] ?? ext[key]
const errText = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback)
function failure(e: unknown, fallback: string): string {
  if (e instanceof ApiError && e.status === 403) return 'You do not have permission to change preview limits. Only platform admins can.'
  return errText(e, fallback)
}

function LimitInputs({ idPrefix, errPrefix, draft, onChange, bounds, ext, bad, placeholders, disabled }: {
  idPrefix: string
  errPrefix: string
  draft: Draft
  onChange: (key: PreviewLimitKey, v: string) => void
  bounds: PreviewLimits['bounds']
  ext: PathErrors
  bad: Partial<Record<PreviewLimitKey, string>>
  placeholders?: Partial<PreviewLimitValues>
  disabled?: boolean
}) {
  return (
    <div className="bh-grid">
      {LIMIT_FIELDS.map((f) => {
        const [min, max] = bounds[f.key] ?? [0, 0]
        const m = [...(msgs(ext, errPrefix, f.key) ?? []), ...(bad[f.key] ? [bad[f.key]!] : [])]
        return (
          <Field key={f.key} id={`${idPrefix}-${f.key}`} label={`${f.label} (${f.unit})`} messages={m} hint={`Allowed ${min} to ${max}.`}>
            {(p) => (
              <input
                {...p}
                type="number"
                inputMode="decimal"
                step={f.key === 'cpus' ? 0.1 : 1}
                min={min}
                max={max}
                disabled={disabled}
                placeholder={placeholders?.[f.key] !== undefined ? `default ${placeholders[f.key]}` : undefined}
                value={draft[f.key]}
                onChange={(e) => onChange(f.key, e.target.value)}
              />
            )}
          </Field>
        )
      })}
    </div>
  )
}

function OrgEditor({ org, bounds, defaults, readOnly, onSaved, onClose }: {
  org: { id: string; name: string }
  bounds: PreviewLimits['bounds']
  defaults: PreviewLimitValues
  readOnly: boolean
  onSaved: () => void
  onClose: () => void
}) {
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [loadErr, setLoadErr] = useState('')
  const [enabled, setEnabled] = useState(true)
  const [above, setAbove] = useState(false)
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const [note, setNote] = useState('')
  const [ext, setExt] = useState<PathErrors>({})
  const [bad, setBad] = useState<Partial<Record<PreviewLimitKey, string>>>({})
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => { alive.current = false }
  }, [])
  const load = useCallback(() => {
    setState('loading')
    api.adminPreviewOrgLimits(org.id).then((o) => {
      if (!alive.current) return
      setEnabled(o.enabled)
      setAbove(o.allow_above_default ?? false)
      setDraft(draftOf(o.overrides))
      setNote(o.note ?? '')
      setState('ready')
    }).catch((e) => {
      if (!alive.current) return
      setLoadErr(errText(e, 'Could not load'))
      setState('error')
    })
  }, [org.id])
  useEffect(load, [load])

  async function save() {
    const { ok, bad: b } = numbersFromDraft(draft)
    setBad(b)
    setExt({})
    setError('')
    if (Object.keys(b).length) return
    setSaving(true)
    try {
      await api.adminSetPreviewOrgLimits(org.id, { enabled, allow_above_default: above, overrides: ok, note: note.trim() === '' ? null : note.trim() })
      if (alive.current) onSaved()
    } catch (e) {
      if (!alive.current) return
      if (e instanceof ApiError && e.status === 422) setExt(issuesFromDetail(e.details))
      setError(failure(e, 'Could not save'))
    } finally {
      if (alive.current) setSaving(false)
    }
  }

  return (
    <section className="card" aria-labelledby="pl-org-title" data-testid="org-editor">
      <h2 id="pl-org-title">Override for {org.name}</h2>
      {state === 'loading' && <p className="empty-state" role="status">Loading…</p>}
      {state === 'error' && <LoadFailed what="this override" message={loadErr} onRetry={load} />}
      {state === 'ready' && (
        <>
          <p className="muted">Leave a field empty to use the platform default. Switching previews off blocks new previews for this organization (already running ones are not stopped).</p>
          <label>
            <input type="checkbox" role="switch" checked={enabled} disabled={readOnly} onChange={(e) => setEnabled(e.target.checked)} /> Previews enabled for this organization
          </label>
          <label>
            <input type="checkbox" checked={above} disabled={readOnly} onChange={(e) => setAbove(e.target.checked)} /> Allow values above the platform default
          </label>
          <LimitInputs idPrefix="pl-org" errPrefix="overrides" draft={draft} bounds={bounds} ext={ext} bad={bad} placeholders={defaults} disabled={readOnly}
            onChange={(k, v) => setDraft((d) => ({ ...d, [k]: v }))} />
          <Field id="pl-org-note" label="Note (why this override exists)" messages={ext.note}>
            {(p) => <input {...p} type="text" maxLength={500} disabled={readOnly} value={note} onChange={(e) => setNote(e.target.value)} />}
          </Field>
          {error && <div role="alert" data-variant="danger" className="bh-alert" data-testid="org-error">{error}</div>}
          <div className="bh-actions">
            {!readOnly && <button onClick={() => void save()} disabled={saving}>{saving ? 'Saving…' : 'Save override'}</button>}
            <button className="outline" onClick={onClose}>Close</button>
          </div>
        </>
      )}
    </section>
  )
}

/** Admin page "Preview limits": kill switch, platform defaults and per-organization overrides (B3-10).
 *  Reading is open to platform staff; changing is for platform admins (readOnly disables every control). */
export function PreviewLimitsPage({ readOnly }: { readOnly: boolean }) {
  const { confirm, toast } = useUi()
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [loadErr, setLoadErr] = useState('')
  const [limits, setLimits] = useState<PreviewLimits | null>(null)
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const [ext, setExt] = useState<PathErrors>({})
  const [bad, setBad] = useState<Partial<Record<PreviewLimitKey, string>>>({})
  const [error, setError] = useState('')
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [switchBusy, setSwitchBusy] = useState(false)
  const [switchErr, setSwitchErr] = useState('')
  const [orgs, setOrgs] = useState<AdminOrg[]>([])
  const [rows, setRows] = useState<PreviewOrgLimitsRow[]>([])
  const [offset, setOffset] = useState(0)
  const [total, setTotal] = useState(0)
  const [usage, setUsage] = useState<PreviewUsage | null>(null)
  const [overridesLoading, setOverridesLoading] = useState(true)
  const [editing, setEditing] = useState<{ id: string; name: string } | null>(null)
  const [pickId, setPickId] = useState('')
  const [orgErr, setOrgErr] = useState('')
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => { alive.current = false }
  }, [])

  const PAGE = 25
  const loadOverrides = useCallback(async (at = 0) => {
    setOverridesLoading(true)
    setOrgErr('')
    try {
      const page = await api.adminPreviewOrgList(PAGE, at)
      if (!alive.current) return
      setRows(page.items)
      setTotal(page.total)
      setOffset(page.offset)
    } catch (e) {
      if (alive.current) setOrgErr(errText(e, 'Could not load the overrides'))
    } finally {
      if (alive.current) setOverridesLoading(false)
    }
  }, [])
  const loadPicker = useCallback(() => {
    api.adminOrganizations('', 50, 0).then((p) => alive.current && setOrgs(p.items)).catch(() => undefined)
  }, [])
  const loadUsage = useCallback(() => {
    api.adminPreviewUsage().then((u) => alive.current && setUsage(u)).catch(() => alive.current && setUsage(null))
  }, [])

  const load = useCallback(() => {
    setState('loading')
    api.adminPreviewLimits().then((l) => {
      if (!alive.current) return
      setLimits(l)
      setDraft(draftOf(l.defaults))
      setState('ready')
    }).catch((e) => {
      if (!alive.current) return
      setLoadErr(errText(e, 'Could not load'))
      setState('error')
    })
    void loadOverrides(0)
    loadPicker()
    loadUsage()
  }, [loadOverrides, loadPicker, loadUsage])
  useEffect(load, [load])

  async function saveDefaults() {
    if (!limits) return
    const { ok, bad: b } = numbersFromDraft(draft, limits.defaults)
    setBad(b)
    setExt({})
    setError('')
    setNote('')
    if (Object.keys(b).length) return
    if (!Object.keys(ok).length) { setNote('Nothing changed.'); return }
    setSaving(true)
    try {
      const saved = await api.adminUpdatePreviewLimits({ defaults: ok })
      if (!alive.current) return
      setLimits(saved)
      setDraft(draftOf(saved.defaults))
      setNote('Saved.')
    } catch (e) {
      if (!alive.current) return
      if (e instanceof ApiError && e.status === 422) setExt(issuesFromDetail(e.details))
      setError(e instanceof ApiError && e.status === 409 ? 'Someone else changed these limits. Reload and try again.' : failure(e, 'Could not save'))
    } finally {
      if (alive.current) setSaving(false)
    }
  }

  async function toggleSwitch() {
    if (!limits) return
    const turnOn = !limits.kill_switch
    const ok = await confirm(turnOn
      ? { title: 'Turn the preview kill switch on?', message: 'Every preview stops answering requests right away and nobody can start a new one until you turn it off again.', confirmLabel: 'Stop all previews', danger: true }
      : { title: 'Turn previews back on?', message: 'Previews answer requests again and people can start new ones.', confirmLabel: 'Allow previews' })
    if (!ok) return
    setSwitchBusy(true)
    setSwitchErr('')
    try {
      const saved = await api.adminUpdatePreviewLimits({ kill_switch: turnOn })
      if (!alive.current) return
      setLimits(saved)
      toast(turnOn ? 'Kill switch is on: previews are stopped.' : 'Kill switch is off: previews are allowed.', 'success')
    } catch (e) {
      if (alive.current) setSwitchErr(failure(e, 'Could not change the kill switch'))
    } finally {
      if (alive.current) setSwitchBusy(false)
    }
  }

  async function removeOverride(id: string, name: string) {
    const ok = await confirm({ title: `Remove the override for ${name}?`, message: 'The organization goes back to the platform defaults.', confirmLabel: 'Remove', danger: true })
    if (!ok) return
    setOrgErr('')
    try {
      await api.adminClearPreviewOrgLimits(id)
      if (!alive.current) return
      toast('Override removed.', 'success')
      void loadOverrides(rows.length === 1 && offset > 0 ? offset - PAGE : offset)
      loadUsage()
    } catch (e) {
      if (alive.current) setOrgErr(failure(e, 'Could not remove the override'))
    }
  }

  const nameOf = (id: string) => rows.find((o) => o.organization_id === id)?.organization_name ?? orgs.find((o) => o.id === id)?.name ?? id
  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
  function startAdd() {
    const id = pickId.trim()
    if (!UUID.test(id)) { setOrgErr('Pick an organization or paste its id (a UUID).'); return }
    setOrgErr('')
    setEditing({ id, name: nameOf(id) })
  }
  const dirty = limits ? Object.keys(numbersFromDraft(draft, limits.defaults).ok).length > 0 : false

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Preview limits</h1>
          <p>Previews are for trying a project, not for production. These limits apply to every preview.{readOnly && ' You can read these settings; only platform admins can change them.'}</p>
        </div>
      </div>
      {state === 'loading' && <p className="empty-state" role="status">Loading…</p>}
      {state === 'error' && <LoadFailed what="the preview limits" message={loadErr} onRetry={load} />}
      {state === 'ready' && limits && (
        <>
          <section className="card" aria-labelledby="pl-kill-title" data-testid="kill-switch">
            <h2 id="pl-kill-title">Kill switch</h2>
            <p role="status" data-testid="kill-state">
              {limits.kill_switch ? 'ON: all previews are stopped and new ones are refused.' : 'Off: previews run normally.'}
            </p>
            <button
              className={limits.kill_switch ? undefined : 'outline'}
              data-variant={limits.kill_switch ? undefined : 'danger'}
              onClick={() => void toggleSwitch()}
              disabled={readOnly || switchBusy}
            >
              {limits.kill_switch ? 'Turn kill switch off' : 'Turn kill switch on'}
            </button>
            {switchErr && <div role="alert" data-variant="danger" className="bh-alert" data-testid="switch-error">{switchErr}</div>}
          </section>

          <section className="card" aria-labelledby="pl-def-title">
            <h2 id="pl-def-title">Platform defaults</h2>
            <p className="muted">Used by every organization without an override. Changes apply to new and waking previews.</p>
            <LimitInputs idPrefix="pl-def" errPrefix="defaults" draft={draft} bounds={limits.bounds} ext={ext} bad={bad} disabled={readOnly}
              onChange={(k, v) => { setDraft((d) => ({ ...d, [k]: v })); setNote(''); setExt({}) }} />
            <div className="bh-savebar">
              {!readOnly && <button onClick={() => void saveDefaults()} disabled={!dirty || saving}>{saving ? 'Saving…' : 'Save defaults'}</button>}
              {!readOnly && <button className="outline" onClick={() => { setDraft(draftOf(limits.defaults)); setExt({}); setBad({}); setError('') }} disabled={!dirty || saving}>Discard changes</button>}
              <span role="status" aria-live="polite">{note && <small data-testid="save-note">{note}</small>}</span>
              {error && <div role="alert" data-variant="danger" className="bh-alert" data-testid="defaults-error">{error}</div>}
            </div>
            {limits.updated_at && <small className="muted">Last changed {new Date(limits.updated_at).toLocaleString()}</small>}
          </section>

          <section className="card" aria-labelledby="pl-orgs-title">
            <h2 id="pl-orgs-title">Organization overrides</h2>
            {usage && (
              <p data-testid="usage" role="status">
                {usage.live} live {usage.live === 1 ? 'preview' : 'previews'} ({usage.running} running), {usage.orgs_with_overrides} {usage.orgs_with_overrides === 1 ? 'organization has' : 'organizations have'} an override.
              </p>
            )}
            {overridesLoading && <p className="empty-state" role="status">Loading overrides…</p>}
            {!overridesLoading && rows.length === 0 && <p className="empty-state" data-testid="no-overrides">No organization has an override. Everyone uses the defaults.</p>}
            {rows.length > 0 && (
              <table data-testid="override-table">
                <caption className="sr-only">Organizations with their own preview limits</caption>
                <thead>
                  <tr><th scope="col">Organization</th><th scope="col">Previews</th><th scope="col">Overridden limits</th><th scope="col">Note</th><th scope="col"><span className="sr-only">Actions</span></th></tr>
                </thead>
                <tbody>
                  {rows.map((o) => (
                    <tr key={o.organization_id}>
                      <th scope="row">{o.organization_name}</th>
                      <td>{o.enabled ? 'Enabled' : 'Disabled'}{o.allow_above_default ? ', above default allowed' : ''}</td>
                      <td>{Object.keys(o.overrides).length ? LIMIT_FIELDS.filter((f) => o.overrides[f.key] !== undefined).map((f) => `${f.label}: ${o.overrides[f.key]}`).join(', ') : 'Defaults'}</td>
                      <td>{o.note ?? ''}</td>
                      <td>
                        <button className="outline small" onClick={() => setEditing({ id: o.organization_id, name: nameOf(o.organization_id) })}>{readOnly ? 'View' : 'Edit'}<span className="sr-only"> {nameOf(o.organization_id)}</span></button>
                        {!readOnly && <button className="outline small" data-variant="danger" onClick={() => void removeOverride(o.organization_id, nameOf(o.organization_id))}>Remove<span className="sr-only"> {nameOf(o.organization_id)}</span></button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {total > PAGE && (
              <nav aria-label="Override pages" className="bh-actions">
                <button className="outline small" disabled={offset === 0 || overridesLoading} onClick={() => void loadOverrides(Math.max(0, offset - PAGE))}>Previous</button>
                <small className="muted" data-testid="override-range">{offset + 1} to {Math.min(offset + PAGE, total)} of {total}</small>
                <button className="outline small" disabled={offset + PAGE >= total || overridesLoading} onClick={() => void loadOverrides(offset + PAGE)}>Next</button>
              </nav>
            )}
            {orgErr && <div role="alert" data-variant="danger" className="bh-alert" data-testid="org-list-error">{orgErr}</div>}
            {!readOnly && (
              <div className="bh-actions">
                <label htmlFor="pl-add-org" className="sr-only">Organization to add</label>
                <select id="pl-add-org" value={orgs.some((o) => o.id === pickId) ? pickId : ''} onChange={(e) => setPickId(e.target.value)}>
                  <option value="">Choose an organization…</option>
                  {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                </select>
                <label htmlFor="pl-add-id" className="sr-only">Or organization id</label>
                <input id="pl-add-id" type="text" placeholder="or paste an organization id" value={pickId} onChange={(e) => setPickId(e.target.value)} />
                <button onClick={startAdd}>Add override</button>
              </div>
            )}
          </section>

          {editing && (
            <OrgEditor key={editing.id} org={editing} bounds={limits.bounds} defaults={limits.defaults} readOnly={readOnly}
              onClose={() => setEditing(null)}
              onSaved={() => { setEditing(null); setPickId(''); toast('Override saved.', 'success'); void loadOverrides(offset); loadUsage() }} />
          )}
        </>
      )}
    </>
  )
}

/** Nav entries and routes for preview limits exist only for platform admins and only with the single flag ui.shell=v2. */
export function showPreviewLimits(role: PlatformRole | undefined, shellV2: boolean): boolean {
  return shellV2 && role === 'platform_admin'
}
