import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, api, saveBlob } from '../../api/client'
import { useRawText } from '../../forms/useRawText'
import { useMyRole } from '../ai/useMyRole'
import { ConflictBanner, Field } from '../behavior/ui'
import {
  FRAMEWORKS, STATUS_TEXT, TREATMENTS, checkDraft, complianceIssues, detailLines, draftFrom, evidenceLabel, listText, nextKey,
  parseList, readControls, toBlock,
  type ControlStatus, type ControlsReport, type Draft, type ExpEntityRow, type ExpFieldRow, type Raw, type RetRow, type Treatment,
} from './complianceLogic'

const msg = (e: unknown, f: string) => (e instanceof Error ? e.message : f)
const SETTINGS_ID = 'compliance-settings'

/** Compliance list input: keeps the raw text while it still parses to the held list (commas and spaces survive each keystroke). */
function ListInput({ id, label, value, onChange, disabled, messages, hint }: {
  id: string; label: string; value: string[]; onChange: (v: string[]) => void; disabled: boolean; messages?: string[]; hint?: string
}) {
  const [text, setText] = useRawText(value, parseList, listText)
  return (
    <Field id={id} label={label} messages={messages} hint={hint}>
      {(p) => <input {...p} value={text} disabled={disabled} onChange={(e) => { setText(e.target.value); onChange(parseList(e.target.value)) }} />}
    </Field>
  )
}

// ── Controls ───────────────────────────────────────────────────────────────
function ControlsPanel({ projectId, refresh }: { projectId: string; refresh: number }) {
  const [fw, setFw] = useState('')
  const [filter, setFilter] = useState<'' | ControlStatus>('')
  const [load, setLoad] = useState<{ s: 'loading' } | { s: 'error'; m: string } | { s: 'ok'; v: ControlsReport }>({ s: 'loading' })
  const [retry, setRetry] = useState(0)
  const [busy, setBusy] = useState(false)
  const [dlError, setDlError] = useState('')
  const [dlNote, setDlNote] = useState('')

  useEffect(() => {
    let dead = false
    setLoad({ s: 'loading' })
    api.getComplianceControls(projectId, fw || undefined).then((j) => {
      if (dead) return
      const r = readControls(j)
      setLoad(r ? { s: 'ok', v: r } : { s: 'error', m: 'The server answered with something that is not a controls report. Check that this is the platform API.' })
    }, (e) => { if (!dead) setLoad({ s: 'error', m: msg(e, 'Could not load the controls') }) })
    return () => { dead = true }
  }, [projectId, fw, refresh, retry])

  async function download() {
    if (!fw) return
    setBusy(true); setDlError(''); setDlNote('')
    try {
      const { blob, filename } = await api.downloadComplianceEvidence(projectId, fw)
      saveBlob(blob, filename)
      setDlNote(`Downloaded ${filename}.`)
    } catch (e) { setDlError(msg(e, 'Could not download the evidence')) } finally { setBusy(false) }
  }

  const fwLabel = FRAMEWORKS.find((f) => f.id === fw)?.label ?? 'All'
  const goSettings = () => {
    const el = document.getElementById(SETTINGS_ID)
    el?.scrollIntoView?.({ block: 'start' })
    el?.focus()
  }
  const shown = load.s === 'ok' ? load.v.controls.filter((c) => !filter || c.status === filter) : []

  return (
    <section aria-labelledby="compliance-controls-h" data-testid="compliance-controls">
      <h2 id="compliance-controls-h">Controls</h2>
      <div className="hstack" role="group" aria-label="Framework">
        {FRAMEWORKS.map((f) => (
          <button key={f.id || 'all'} type="button" className={fw === f.id ? '' : 'outline'} aria-pressed={fw === f.id} onClick={() => setFw(f.id)} data-testid={`fw-${f.id || 'all'}`}>{f.label}</button>
        ))}
      </div>
      {load.s === 'loading' && <p role="status" className="empty-state">Loading controls…</p>}
      {load.s === 'error' && (
        <div role="alert" data-variant="danger" className="bh-alert" data-testid="controls-error">
          Could not load the controls: {load.m} <button type="button" className="small" onClick={() => setRetry((n) => n + 1)}>Try again</button>
        </div>
      )}
      {load.s === 'ok' && (
        <>
          <p data-testid="controls-summary" role="status">
            <strong>{load.v.met}</strong> met, <strong>{load.v.unmet}</strong> unmet, <strong>{load.v.not_applicable}</strong> not applicable.
          </p>
          <div className="hstack">
            <Field id="controls-filter" label="Show">
              {(p) => (
                <select {...p} value={filter} onChange={(e) => setFilter(e.target.value as '' | ControlStatus)}>
                  <option value="">All statuses</option><option value="unmet">Unmet</option><option value="met">Met</option><option value="not_applicable">Not applicable</option>
                </select>
              )}
            </Field>
            <button type="button" onClick={() => void download()} disabled={busy || !fw} data-testid="evidence-download" aria-describedby="evidence-hint">{busy ? 'Preparing…' : `Download evidence (${fwLabel})`}</button>
          </div>
          {!fw && <p id="evidence-hint" className="muted small-text" data-testid="evidence-hint">Pick a framework above to download its evidence bundle.</p>}
          {dlError && <div role="alert" data-variant="danger" className="bh-alert" data-testid="evidence-error">{dlError}</div>}
          <p role="status" aria-live="polite">{dlNote && <small data-testid="evidence-note">{dlNote}</small>}</p>
          {shown.length === 0 ? (
            <p className="empty-state" data-testid="controls-empty">{load.v.controls.length === 0 ? 'No controls are mapped for this framework.' : 'No controls match this filter.'}</p>
          ) : (
            <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Controls table">
              <table className="stage-table" data-testid="controls-table">
                <caption className="sr-only">Compliance controls and their status</caption>
                <thead><tr><th scope="col">Control</th><th scope="col">Status</th><th scope="col">Reason</th><th scope="col">Evidence</th><th scope="col">Proving tests</th></tr></thead>
                <tbody>
                  {shown.map((c) => (
                    <tr key={`${c.framework}:${c.id}`} data-testid="control-row" data-status={c.status}>
                      <th scope="row">{c.id}<br /><small className="muted">{c.framework.toUpperCase()}</small><br />{c.title}{c.description && <small className="muted"> {c.description}</small>}</th>
                      <td data-testid="control-status"><span aria-hidden="true">{STATUS_TEXT[c.status].icon} </span>{STATUS_TEXT[c.status].text}</td>
                      <td>
                        {c.reason}
                        {c.status === 'unmet' && (
                          <> <button type="button" className="ghost small" onClick={goSettings} data-testid="goto-settings" aria-label={`Switch it on in Settings to fix ${c.id}`}>Switch it on in Settings</button></>
                        )}
                      </td>
                      <td>{c.evidence.length === 0 ? <span className="muted">None</span> : <ul>{c.evidence.map((e, i) => <li key={i}>{evidenceLabel(e)}</li>)}</ul>}</td>
                      <td>{c.tests.length === 0 ? <span className="muted">None</span> : <ul>{c.tests.map((t, i) => <li key={i}><code>{t.file}::{t.name}</code></li>)}</ul>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  )
}

// ── Settings ───────────────────────────────────────────────────────────────
type Load = { s: 'loading' } | { s: 'error'; m: string } | { s: 'ok' }

function SettingsPanel({ projectId, readOnly, onSaved }: { projectId: string; readOnly: boolean; onSaved: () => void }) {
  const [load, setLoad] = useState<Load>({ s: 'loading' })
  const [raw, setRaw] = useState<Raw | null>(null)
  const [version, setVersion] = useState(0)
  const [d, setD] = useState<Draft>(() => draftFrom(null))
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [errs, setErrs] = useState<Record<string, string>>({})
  const [saveError, setSaveError] = useState('')
  const [serverIssues, setServerIssues] = useState<string[]>([])
  const [note, setNote] = useState('')
  const [conflict, setConflict] = useState(false)
  const [retry, setRetry] = useState(0)
  const latest = useRef(d)
  latest.current = d

  useEffect(() => {
    let dead = false
    setLoad({ s: 'loading' })
    api.getBlock(projectId, 'compliance').then((r) => {
      if (dead) return
      const block = r.compliance
      if (block !== null && block !== undefined && (typeof block !== 'object' || Array.isArray(block))) { setLoad({ s: 'error', m: 'The server answered with something that is not the compliance settings.' }); return }
      setRaw((block as Raw | null | undefined) ?? null)
      setVersion(typeof r.version === 'number' ? r.version : 0)
      setD(draftFrom((block as Raw | null | undefined) ?? null))
      setDirty(false); setConflict(false); setErrs({}); setSaveError(''); setNote(''); setServerIssues([])
      setLoad({ s: 'ok' })
    }, (e) => { if (!dead) setLoad({ s: 'error', m: msg(e, 'Could not load the compliance settings') }) })
    return () => { dead = true }
  }, [projectId, retry])

  const edit = (f: (x: Draft) => Draft) => { setD((x) => f(x)); setDirty(true); setNote(''); setSaveError('') }

  async function save() {
    const cur = latest.current
    const found = checkDraft(cur)
    setErrs(found)
    if (Object.keys(found).length) { setSaveError('Fix the highlighted fields before saving.'); return }
    setSaving(true); setSaveError(''); setNote(''); setServerIssues([])
    try {
      const r = await api.putBlock(projectId, 'compliance', { compliance: toBlock(cur, raw), expected_version: version })
      const block = r.compliance
      if (typeof r.version !== 'number' || (block !== null && typeof block !== 'object')) throw new Error('The server answered with something unexpected.')
      setRaw((block as Raw | null) ?? null)
      setVersion(r.version)
      setDirty(latest.current !== cur)
      setNote(`Saved (version ${r.version}).`)
      onSaved()
      try { setServerIssues(complianceIssues((await api.getBehaviorIssues(projectId)).issues)) } catch (e) { setServerIssues([`Could not check the saved settings with the validator: ${msg(e, 'request failed')}`]) }
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setConflict(true)
      else {
        setSaveError(msg(e, 'Could not save'))
        if (e instanceof ApiError) setServerIssues(detailLines(e.details))
      }
    } finally { setSaving(false) }
  }

  const E = (k: string) => (errs[k] ? [errs[k]] : undefined)
  const off = readOnly || saving
  const setRet = (k: number, p: Partial<RetRow>) => edit((x) => ({ ...x, retention: x.retention.map((r) => (r.k === k ? { ...r, ...p } : r)) }))
  const setFld = (k: number, p: Partial<ExpFieldRow>) => edit((x) => ({ ...x, expFields: x.expFields.map((r) => (r.k === k ? { ...r, ...p } : r)) }))
  const setEnt = (k: number, p: Partial<ExpEntityRow>) => edit((x) => ({ ...x, expEntities: x.expEntities.map((r) => (r.k === k ? { ...r, ...p } : r)) }))
  const keepIdentifier = d.expFields.some((f) => f.treatment === 'keep')

  return (
    <section aria-labelledby={SETTINGS_ID} data-testid="compliance-settings">
      <h2 id={SETTINGS_ID} tabIndex={-1}>Settings</h2>
      {load.s === 'loading' && <p role="status" className="empty-state">Loading settings…</p>}
      {load.s === 'error' && (
        <div role="alert" data-variant="danger" className="bh-alert" data-testid="settings-error">
          Could not load the compliance settings: {load.m} <button type="button" className="small" onClick={() => setRetry((n) => n + 1)}>Try again</button>
        </div>
      )}
      {load.s === 'ok' && (
        <form onSubmit={(e) => { e.preventDefault(); if (!off) void save() }} noValidate>
          {readOnly && <p className="muted" data-testid="settings-readonly">You have the viewer role: these settings are read-only.</p>}
          {conflict && <ConflictBanner onReload={() => setRetry((n) => n + 1)} />}
          <label><input type="checkbox" role="switch" checked={d.enabled} disabled={off} onChange={(e) => edit((x) => ({ ...x, enabled: e.target.checked }))} data-testid="cmp-enabled" /> Compliance runtime enabled</label>
          <ListInput id="cmp-roles" label="Administrator roles" hint="Roles that administer holds, retention runs and exports. Separate with commas." value={d.roles} disabled={off} onChange={(v) => edit((x) => ({ ...x, roles: v }))} />

          <h3>Retention rules</h3>
          {d.retention.length === 0 && <p className="muted">No retention rules.</p>}
          {d.retention.map((r, i) => (
            <fieldset key={r.k} data-testid="retention-row">
              <legend>Retention rule {i + 1}</legend>
              <Field id={`ret-${r.k}-entity`} label="Entity" messages={E(`ret.${r.k}.entity`)}>{(p) => <input {...p} value={r.entity} disabled={off} onChange={(e) => setRet(r.k, { entity: e.target.value })} />}</Field>
              <Field id={`ret-${r.k}-days`} label="Keep for (days)" messages={E(`ret.${r.k}.days`)}>{(p) => <input {...p} inputMode="numeric" value={r.days} disabled={off} onChange={(e) => setRet(r.k, { days: e.target.value })} />}</Field>
              <Field id={`ret-${r.k}-date`} label="Date field" messages={E(`ret.${r.k}.date_field`)}>{(p) => <input {...p} value={r.date_field} disabled={off} onChange={(e) => setRet(r.k, { date_field: e.target.value })} />}</Field>
              <Field id={`ret-${r.k}-action`} label="Action">{(p) => (
                <select {...p} value={r.action} disabled={off} onChange={(e) => setRet(r.k, { action: e.target.value as 'purge' | 'anonymise' })}><option value="purge">Purge</option><option value="anonymise">Anonymise</option></select>
              )}</Field>
              {r.action === 'anonymise' && <ListInput id={`ret-${r.k}-anon`} label="Fields to anonymise" value={r.anonymise_fields} disabled={off} messages={E(`ret.${r.k}.anonymise_fields`)} onChange={(v) => setRet(r.k, { anonymise_fields: v })} />}
              {!readOnly && <button type="button" className="outline small" disabled={saving} onClick={() => edit((x) => ({ ...x, retention: x.retention.filter((y) => y.k !== r.k) }))} aria-label={`Remove retention rule ${i + 1}`}>Remove</button>}
            </fieldset>
          ))}
          {!readOnly && <button type="button" className="outline" disabled={saving} data-testid="add-retention" onClick={() => edit((x) => ({ ...x, retention: [...x.retention, { k: nextKey(), entity: '', days: '', date_field: 'created_at', action: 'purge', anonymise_fields: [] }] }))}>Add retention rule</button>}

          <h3>Consent purposes</h3>
          <ListInput id="cmp-purposes" label="Purposes" hint="Separate with commas; each purpose once." value={d.purposes} disabled={off} messages={E('purposes')} onChange={(v) => edit((x) => ({ ...x, purposes: v }))} />

          <h3>Break-glass access</h3>
          <label><input type="checkbox" role="switch" checked={d.bgEnabled} disabled={off} onChange={(e) => edit((x) => ({ ...x, bgEnabled: e.target.checked }))} data-testid="cmp-bg-enabled" /> Break-glass enabled</label>
          <ListInput id="cmp-bg-roles" label="Roles that may ask" value={d.bgRoles} disabled={off} onChange={(v) => edit((x) => ({ ...x, bgRoles: v }))} />
          <Field id="cmp-bg-minutes" label="Grant lasts (minutes)" hint="5 to 240" messages={E('bgMinutes')}>{(p) => <input {...p} inputMode="numeric" value={d.bgMinutes} disabled={off} onChange={(e) => edit((x) => ({ ...x, bgMinutes: e.target.value }))} />}</Field>

          <h3>De-identified export</h3>
          <p className="muted" data-testid="keep-warning">Fields you do not list are dropped. Treatment &quot;keep&quot; on a direct identifier (name, email, phone and similar) is refused by the server when you save.{keepIdentifier ? ' You have fields set to keep: check they are not identifiers.' : ''}</p>
          {d.expEntities.map((x, i) => (
            <fieldset key={x.k} data-testid="export-entity-row">
              <legend>Exported entity {i + 1}</legend>
              <Field id={`ent-${x.k}-entity`} label="Entity" messages={E(`ent.${x.k}.entity`)}>{(p) => <input {...p} value={x.entity} disabled={off} onChange={(e) => setEnt(x.k, { entity: e.target.value })} />}</Field>
              <Field id={`ent-${x.k}-subject`} label="Subject field" hint="The field holding the person the row is about (for consent)">{(p) => <input {...p} value={x.subject_field} disabled={off} onChange={(e) => setEnt(x.k, { subject_field: e.target.value })} />}</Field>
              {!readOnly && <button type="button" className="outline small" disabled={saving} onClick={() => edit((y) => ({ ...y, expEntities: y.expEntities.filter((z) => z.k !== x.k) }))} aria-label={`Remove exported entity ${i + 1}`}>Remove</button>}
            </fieldset>
          ))}
          {!readOnly && <button type="button" className="outline" disabled={saving} data-testid="add-export-entity" onClick={() => edit((x) => ({ ...x, expEntities: [...x.expEntities, { k: nextKey(), entity: '', subject_field: '' }] }))}>Add exported entity</button>}
          {d.expFields.map((f, i) => (
            <fieldset key={f.k} data-testid="export-field-row">
              <legend>Export field {i + 1}</legend>
              <Field id={`exp-${f.k}-entity`} label="Entity" messages={E(`exp.${f.k}.entity`)}>{(p) => <input {...p} value={f.entity} disabled={off} onChange={(e) => setFld(f.k, { entity: e.target.value })} />}</Field>
              <Field id={`exp-${f.k}-field`} label="Field" messages={E(`exp.${f.k}.field`)}>{(p) => <input {...p} value={f.field} disabled={off} onChange={(e) => setFld(f.k, { field: e.target.value })} />}</Field>
              <Field id={`exp-${f.k}-treat`} label="Treatment">{(p) => (
                <select {...p} value={f.treatment} disabled={off} onChange={(e) => setFld(f.k, { treatment: e.target.value as Treatment })}>{TREATMENTS.map((t) => <option key={t} value={t}>{t}</option>)}</select>
              )}</Field>
              {!readOnly && <button type="button" className="outline small" disabled={saving} onClick={() => edit((x) => ({ ...x, expFields: x.expFields.filter((y) => y.k !== f.k) }))} aria-label={`Remove export field ${i + 1}`}>Remove</button>}
            </fieldset>
          ))}
          {!readOnly && <button type="button" className="outline" disabled={saving} data-testid="add-export-field" onClick={() => edit((x) => ({ ...x, expFields: [...x.expFields, { k: nextKey(), entity: '', field: '', treatment: 'drop' }] }))}>Add export field</button>}
          <Field id="cmp-consent-purpose" label="Export consent purpose" hint="Rows of subjects without active consent for this purpose are left out. Leave empty for none.">{(p) => <input {...p} value={d.consentPurpose} disabled={off} onChange={(e) => edit((x) => ({ ...x, consentPurpose: e.target.value }))} />}</Field>

          {!readOnly && (
            <div className="bh-savebar">
              <button type="submit" disabled={!dirty || saving} data-testid="settings-save">{saving ? 'Saving…' : 'Save'}</button>
              <button type="button" className="outline" disabled={!dirty || saving} onClick={() => setRetry((n) => n + 1)}>Discard changes</button>
              {dirty && !saving && <small className="muted">Unsaved changes</small>}
            </div>
          )}
          <span role="status" aria-live="polite">{note && <small data-testid="settings-note">{note}</small>}</span>
          {saveError && <div role="alert" data-variant="danger" className="bh-alert" data-testid="settings-save-error">{saveError}</div>}
          {serverIssues.length > 0 && (
            <div role="alert" data-variant="danger" className="bh-alert" data-testid="server-issues">
              The server reported {serverIssues.length === 1 ? 'a problem' : 'problems'}:
              <ul>{serverIssues.map((m, i) => <li key={i}>{m}</li>)}</ul>
            </div>
          )}
        </form>
      )}
    </section>
  )
}

// ── Regulated (read-only) ──────────────────────────────────────────────────
function RegulatedPanel({ projectId, refresh }: { projectId: string; refresh: number }) {
  const [load, setLoad] = useState<{ s: 'loading' } | { s: 'error'; m: string } | { s: 'ok'; enabled: boolean; provider: string; fields: number; configured: boolean }>({ s: 'loading' })
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    let dead = false
    setLoad({ s: 'loading' })
    api.getBlock(projectId, 'regulated').then((r) => {
      if (dead) return
      const b = r.regulated
      if (b === null || b === undefined) { setLoad({ s: 'ok', enabled: false, provider: '', fields: 0, configured: false }); return }
      if (typeof b !== 'object' || Array.isArray(b)) { setLoad({ s: 'error', m: 'The server answered with something that is not the regulated settings.' }); return }
      const x = b as Raw
      setLoad({ s: 'ok', enabled: x.enabled === true, provider: typeof x.key_provider === 'string' ? x.key_provider : '', fields: Array.isArray(x.fields) ? x.fields.length : 0, configured: true })
    }, (e) => { if (!dead) setLoad({ s: 'error', m: msg(e, 'Could not load the regulated settings') }) })
    return () => { dead = true }
  }, [projectId, refresh, retry])
  const rotate = useCallback(() => setRetry((n) => n + 1), [])
  return (
    <section aria-labelledby="compliance-regulated-h" data-testid="compliance-regulated">
      <h2 id="compliance-regulated-h">Regulated mode</h2>
      {load.s === 'loading' && <p role="status" className="empty-state">Loading…</p>}
      {load.s === 'error' && <div role="alert" data-variant="danger" className="bh-alert" data-testid="regulated-error">Could not load the regulated settings: {load.m} <button type="button" className="small" onClick={rotate}>Try again</button></div>}
      {load.s === 'ok' && (
        <dl data-testid="regulated-summary">
          <dt>Status</dt><dd>{load.configured ? (load.enabled ? 'On' : 'Off') : 'Not configured'}</dd>
          <dt>Key provider</dt><dd>{load.provider || 'None'}</dd>
          <dt>Protected fields</dt><dd>{load.fields}</dd>
        </dl>
      )}
      <p className="muted small-text">Shown for reference only. Keys are kept outside the platform and are never shown or entered here.</p>
    </section>
  )
}

/** Secure > Compliance: control mapping + evidence (D47), the compliance spec block (retention, consent, break-glass, de-identified export),
 *  and a read-only look at regulated mode. Talks to the platform API, not the generated app. */
export function CompliancePage({ projectId }: { projectId: string }) {
  const role = useMyRole(projectId)
  const [refresh, setRefresh] = useState(0)
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Compliance</h1>
          <p>Which SOC 2, HIPAA and PCI controls your project meets, the evidence and tests that prove them, and the settings that switch them on.</p>
        </div>
      </div>
      <ControlsPanel projectId={projectId} refresh={refresh} />
      <SettingsPanel projectId={projectId} readOnly={role === 'viewer'} onSaved={() => setRefresh((n) => n + 1)} />
      <RegulatedPanel projectId={projectId} refresh={refresh} />
    </>
  )
}
