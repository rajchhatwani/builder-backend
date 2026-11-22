import { useEffect, useRef, useState } from 'react'
import { ApiError, api } from '../../api/client'
import { useMyRole } from '../ai/useMyRole'
import { ConflictBanner, Field } from '../behavior/ui'
import { PreviewSessionGate } from '../preview/PreviewSessionGate'
import type { PreviewSession } from '../preview/previewSession'
import { usePreviewSession } from '../preview/usePreviewSession'
import { ListInput } from './ListInput'
import { SecretPanel } from './SecretPanel'
import {
  KEY_STATUS_TEXT, auditDetail, checkDraft, detailLines, draftFrom, nextKey, ok, platformCall, platformError, platformIssues, readAudit, readCatalogue,
  readKeyCreated, readKeys, shortWhen, toBlock,
  type AppRow, type AuditRow, type Catalogue, type Draft, type EntityRow, type KeyCreated, type KeyRow, type Raw,
} from './platformLogic'

const msg = (e: unknown, f: string) => (e instanceof Error ? e.message : f)
type Load<T> = { s: 'loading' } | { s: 'error'; m: string } | { s: 'ok'; v: T }

// ── Settings (builder side) ────────────────────────────────────────────────
function SettingsPanel({ projectId, readOnly }: { projectId: string; readOnly: boolean }) {
  const [load, setLoad] = useState<Load<null>>({ s: 'loading' })
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
    api.getBlock(projectId, 'api_platform').then((r) => {
      if (dead) return
      const block = r.api_platform
      if (block !== null && block !== undefined && (typeof block !== 'object' || Array.isArray(block))) { setLoad({ s: 'error', m: 'The server answered with something that is not the API platform settings.' }); return }
      setRaw((block as Raw | null | undefined) ?? null)
      setVersion(typeof r.version === 'number' ? r.version : 0)
      setD(draftFrom((block as Raw | null | undefined) ?? null))
      setDirty(false); setConflict(false); setErrs({}); setSaveError(''); setNote(''); setServerIssues([])
      setLoad({ s: 'ok', v: null })
    }, (e) => { if (!dead) setLoad({ s: 'error', m: msg(e, 'Could not load the API platform settings') }) })
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
      const r = await api.putBlock(projectId, 'api_platform', { api_platform: toBlock(cur, raw), expected_version: version })
      const block = r.api_platform
      if (typeof r.version !== 'number' || (block !== null && typeof block !== 'object')) throw new Error('The server answered with something unexpected.')
      setRaw((block as Raw | null) ?? null)
      setVersion(r.version)
      setDirty(latest.current !== cur)
      setNote(`Saved (version ${r.version}).`)
      try { setServerIssues(platformIssues((await api.getBehaviorIssues(projectId)).issues)) } catch (e) { setServerIssues([`Could not check the saved settings with the validator: ${msg(e, 'request failed')}`]) }
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
  const setEnt = (k: number, p: Partial<EntityRow>) => edit((x) => ({ ...x, entities: x.entities.map((r) => (r.k === k ? { ...r, ...p } : r)) }))
  const setApp = (k: number, p: Partial<AppRow>) => edit((x) => ({ ...x, apps: x.apps.map((r) => (r.k === k ? { ...r, ...p } : r)) }))

  return (
    <section aria-labelledby="apikeys-settings-h" data-testid="apikeys-settings">
      <h2 id="apikeys-settings-h">Settings</h2>
      {load.s === 'loading' && <p role="status" className="empty-state">Loading settings…</p>}
      {load.s === 'error' && (
        <div role="alert" data-variant="danger" className="bh-alert" data-testid="settings-error">
          Could not load the API platform settings: {load.m} <button type="button" className="small" onClick={() => setRetry((n) => n + 1)}>Try again</button>
        </div>
      )}
      {load.s === 'ok' && (
        <form onSubmit={(e) => { e.preventDefault(); if (!off) void save() }} noValidate>
          {readOnly && <p className="muted" data-testid="settings-readonly">You have the viewer role: these settings are read-only.</p>}
          {conflict && <ConflictBanner onReload={() => setRetry((n) => n + 1)} />}
          <label><input type="checkbox" role="switch" checked={d.enabled} disabled={off} onChange={(e) => edit((x) => ({ ...x, enabled: e.target.checked }))} data-testid="ap-enabled" /> Public API and apps enabled</label>
          <ListInput id="ap-roles" label="Roles that manage keys and apps" hint="Only these roles open the key and app screens (nobody else does). Separate with commas." value={d.roles} disabled={off} onChange={(v) => edit((x) => ({ ...x, roles: v }))} />
          <Field id="ap-rate" label="Rate limit (production keys)" hint="For example 60/minute" messages={E('rateLimit')}>{(p) => <input {...p} value={d.rateLimit} disabled={off} onChange={(e) => edit((x) => ({ ...x, rateLimit: e.target.value }))} />}</Field>
          <Field id="ap-srate" label="Rate limit (sandbox keys)" hint="For example 20/minute" messages={E('sandboxRateLimit')}>{(p) => <input {...p} value={d.sandboxRateLimit} disabled={off} onChange={(e) => edit((x) => ({ ...x, sandboxRateLimit: e.target.value }))} />}</Field>
          <Field id="ap-ttl" label="Key lifetime (days)" hint="1 to 365" messages={E('ttl')}>{(p) => <input {...p} inputMode="numeric" value={d.ttl} disabled={off} onChange={(e) => edit((x) => ({ ...x, ttl: e.target.value }))} />}</Field>

          <h3>Exposed entities</h3>
          <p className="muted small-text">Nothing is shared by default: list each entity and the exact fields the public API returns.</p>
          {errs.entities && <p className="bh-error">{errs.entities}</p>}
          {d.entities.length === 0 && <p className="muted">No entities are exposed.</p>}
          {d.entities.map((x, i) => (
            <fieldset key={x.k} data-testid="entity-row">
              <legend>Exposed entity {i + 1}</legend>
              <Field id={`ent-${x.k}-entity`} label="Entity" messages={E(`ent.${x.k}.entity`)}>{(p) => <input {...p} value={x.entity} disabled={off} onChange={(e) => setEnt(x.k, { entity: e.target.value })} />}</Field>
              <ListInput id={`ent-${x.k}-fields`} label="Fields returned" hint="Separate with commas. id is always included." value={x.fields} disabled={off} messages={E(`ent.${x.k}.fields`)} onChange={(v) => setEnt(x.k, { fields: v })} />
              <label><input type="checkbox" checked={x.sandbox} disabled={off} onChange={(e) => setEnt(x.k, { sandbox: e.target.checked })} /> Readable with a sandbox key too</label>
              {!readOnly && <button type="button" className="outline small" disabled={saving} onClick={() => edit((y) => ({ ...y, entities: y.entities.filter((z) => z.k !== x.k) }))} aria-label={`Remove exposed entity ${i + 1}`}>Remove</button>}
            </fieldset>
          ))}
          {!readOnly && <button type="button" className="outline" disabled={saving} data-testid="add-entity" onClick={() => edit((x) => ({ ...x, entities: [...x.entities, { k: nextKey(), entity: '', fields: [], sandbox: false }] }))}>Add exposed entity</button>}

          <h3>Installable apps</h3>
          {errs.apps && <p className="bh-error">{errs.apps}</p>}
          {d.apps.length === 0 && <p className="muted">No apps.</p>}
          {d.apps.map((a, i) => (
            <fieldset key={a.k} data-testid="app-row">
              <legend>App {i + 1}</legend>
              <Field id={`app-${a.k}-name`} label="Name (slug)" messages={E(`app.${a.k}.name`)}>{(p) => <input {...p} value={a.name} disabled={off} onChange={(e) => setApp(a.k, { name: e.target.value })} />}</Field>
              <Field id={`app-${a.k}-title`} label="Title">{(p) => <input {...p} value={a.title} disabled={off} onChange={(e) => setApp(a.k, { title: e.target.value })} />}</Field>
              <ListInput id={`app-${a.k}-scopes`} label="Entities it may read (scopes)" hint="Each must be an exposed entity above." value={a.scopes} disabled={off} messages={E(`app.${a.k}.scopes`)} onChange={(v) => setApp(a.k, { scopes: v })} />
              <ListInput id={`app-${a.k}-events`} label="Event types it receives" value={a.events} disabled={off} messages={E(`app.${a.k}.events`)} onChange={(v) => setApp(a.k, { events: v })} />
              {!readOnly && <button type="button" className="outline small" disabled={saving} onClick={() => edit((y) => ({ ...y, apps: y.apps.filter((z) => z.k !== a.k) }))} aria-label={`Remove app ${i + 1}`}>Remove</button>}
            </fieldset>
          ))}
          {!readOnly && <button type="button" className="outline" disabled={saving} data-testid="add-app" onClick={() => edit((x) => ({ ...x, apps: [...x.apps, { k: nextKey(), name: '', title: '', scopes: [], events: [] }] }))}>Add app</button>}

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

// ── Keys (generated app, through the preview session) ─────────────────────
function KeysBody({ session, onChanged }: { session: PreviewSession; onChanged: () => void }) {
  const { request } = session
  const [cat, setCat] = useState<Load<Catalogue>>({ s: 'loading' })
  const [keys, setKeys] = useState<Load<KeyRow[]>>({ s: 'loading' })
  const [retry, setRetry] = useState(0)
  const [name, setName] = useState('')
  const [scopes, setScopes] = useState<string[]>([])
  const [env, setEnv] = useState<'sandbox' | 'prod'>('sandbox')
  const [ttl, setTtl] = useState('')
  const [formError, setFormError] = useState('')
  const [busy, setBusy] = useState(false)
  const [created, setCreated] = useState<KeyCreated | null>(null)
  const [confirm, setConfirm] = useState<string | null>(null)
  const [actionError, setActionError] = useState('')
  const [note, setNote] = useState('')

  useEffect(() => {
    let dead = false
    setCat({ s: 'loading' }); setKeys({ s: 'loading' })
    void (async () => {
      try {
        const c = await platformCall(request, 'GET', '/platform/catalogue')
        if (dead) return
        if (!ok(c)) { const m = platformError(c.status, c.json); setCat({ s: 'error', m }); setKeys({ s: 'error', m }); return }
        const cv = readCatalogue(c.json)
        if (!cv) { const m = 'The preview answered with something that is not the API platform catalogue. Generate and restart the preview after enabling the platform.'; setCat({ s: 'error', m }); setKeys({ s: 'error', m }); return }
        setCat({ s: 'ok', v: cv })
        const k = await platformCall(request, 'GET', '/platform/keys')
        if (dead) return
        const kv = ok(k) ? readKeys(k.json) : null
        setKeys(kv ? { s: 'ok', v: kv } : { s: 'error', m: ok(k) ? 'The preview answered with something that is not a key list.' : platformError(k.status, k.json) })
      } catch (e) {
        if (dead) return
        const m = msg(e, 'Could not reach the preview app')
        setCat({ s: 'error', m }); setKeys({ s: 'error', m })
      }
    })()
    return () => { dead = true }
  }, [request, retry])

  const reloadKeys = async () => {
    const k = await platformCall(request, 'GET', '/platform/keys')
    const kv = ok(k) ? readKeys(k.json) : null
    if (kv) setKeys({ s: 'ok', v: kv })
  }

  async function create(e: React.FormEvent) {
    e.preventDefault()
    if (busy) return
    const n = name.trim()
    if (!n) { setFormError('Give the key a name.'); return }
    if (scopes.length === 0) { setFormError('Pick at least one entity the key may read.'); return }
    const max = cat.s === 'ok' ? cat.v.key_ttl_days : 365
    if (ttl.trim() && (!/^\d+$/.test(ttl.trim()) || Number(ttl) < 1 || Number(ttl) > max)) { setFormError(`Lifetime must be a whole number of days from 1 to ${max}.`); return }
    setBusy(true); setFormError(''); setActionError(''); setNote('')
    try {
      const body: Record<string, unknown> = { name: n, scopes, environment: env }
      if (ttl.trim()) body.ttl_days = Number(ttl)
      const r = await platformCall(request, 'POST', '/platform/keys', body)
      if (!ok(r)) { setFormError(platformError(r.status, r.json)); return }
      const made = readKeyCreated(r.json)
      if (!made) { setFormError('The preview answered with something unexpected. The key may exist: check the list.'); await reloadKeys(); return }
      setCreated(made)
      setName(''); setScopes([]); setTtl('')
      await reloadKeys()
      onChanged()
    } catch (err) { setFormError(msg(err, 'Could not reach the preview app')) } finally { setBusy(false) }
  }

  async function revoke(id: string) {
    setBusy(true); setActionError(''); setNote('')
    try {
      const r = await platformCall(request, 'POST', `/platform/keys/${encodeURIComponent(id)}/revoke`)
      if (!ok(r)) { setActionError(platformError(r.status, r.json)); return }
      setConfirm(null)
      setNote('Key revoked.')
      await reloadKeys()
      onChanged()
    } catch (err) { setActionError(msg(err, 'Could not reach the preview app')) } finally { setBusy(false) }
  }

  const toggle = (s: string) => setScopes((x) => (x.includes(s) ? x.filter((y) => y !== s) : [...x, s]))

  if (cat.s === 'loading' || keys.s === 'loading') return <p role="status" className="empty-state">Loading keys…</p>
  if (cat.s === 'error' || keys.s === 'error') {
    const m = cat.s === 'error' ? cat.m : keys.s === 'error' ? keys.m : ''
    return (
      <div role="alert" data-variant="danger" className="bh-alert" data-testid="keys-error">
        {m} <button type="button" className="small" onClick={() => setRetry((n) => n + 1)}>Try again</button>
      </div>
    )
  }
  const entities = cat.v.entities
  return (
    <div className="stack">
      {created && (
        <SecretPanel
          title={`Key "${created.name}" created`}
          note="Copy it now. It is shown only once and cannot be shown again."
          secrets={[{ label: 'API key', value: created.key }]}
          onDismiss={() => setCreated(null)}
        />
      )}
      <p className="muted" data-testid="catalogue-limits">Limits: {cat.v.rate_limit} for production keys, {cat.v.sandbox_rate_limit} for sandbox keys. Keys last at most {cat.v.key_ttl_days} days.</p>
      <form onSubmit={(e) => void create(e)} noValidate data-testid="key-form">
        <Field id="key-name" label="Key name">{(p) => <input {...p} value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />}</Field>
        {entities.length === 0 ? <p className="muted">No entity is exposed yet. Add one in Settings and generate again.</p> : (
          <fieldset>
            <legend>Entities the key may read</legend>
            {entities.map((en) => (
              <label key={en.entity}><input type="checkbox" checked={scopes.includes(en.entity)} onChange={() => toggle(en.entity)} data-testid="key-scope" /> {en.entity}{en.sandbox ? ' (sandbox too)' : ''}</label>
            ))}
          </fieldset>
        )}
        <Field id="key-env" label="Environment">{(p) => (
          <select {...p} value={env} onChange={(e) => setEnv(e.target.value as 'sandbox' | 'prod')}><option value="sandbox">Sandbox</option><option value="prod">Production</option></select>
        )}</Field>
        <Field id="key-ttl" label="Lifetime in days (optional)" hint={`1 to ${cat.v.key_ttl_days}; empty uses ${cat.v.key_ttl_days}`}>{(p) => <input {...p} inputMode="numeric" value={ttl} onChange={(e) => setTtl(e.target.value)} />}</Field>
        <button type="submit" disabled={busy} data-testid="key-create">{busy ? 'Working…' : 'Create key'}</button>
        {formError && <div role="alert" data-variant="danger" className="bh-alert" data-testid="key-form-error">{formError}</div>}
      </form>
      {actionError && <div role="alert" data-variant="danger" className="bh-alert" data-testid="key-action-error">{actionError}</div>}
      <p role="status" aria-live="polite">{note && <small data-testid="key-note">{note}</small>}</p>
      {keys.v.length === 0 ? <p className="empty-state" data-testid="keys-empty">No keys yet.</p> : (
        <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Keys table">
          <table className="stage-table" data-testid="keys-table">
            <caption className="sr-only">API keys and installed app tokens</caption>
            <thead><tr><th scope="col">Name</th><th scope="col">Status</th><th scope="col">Key prefix</th><th scope="col">Environment</th><th scope="col">Entities</th><th scope="col">Expires</th><th scope="col">Last used</th><th scope="col">Actions</th></tr></thead>
            <tbody>
              {keys.v.map((k) => (
                <tr key={k.id} data-testid="key-row" data-status={k.status}>
                  <th scope="row">{k.name}{k.app && <small className="muted"> (app {k.app})</small>}</th>
                  <td data-testid="key-status"><span aria-hidden="true">{KEY_STATUS_TEXT[k.status].icon} </span>{KEY_STATUS_TEXT[k.status].text}</td>
                  <td><code>{k.prefix}</code></td>
                  <td>{k.environment}</td>
                  <td>{k.scopes.join(', ')}</td>
                  <td>{shortWhen(k.expires_at)}</td>
                  <td>{k.last_used_at ? shortWhen(k.last_used_at) : 'Never'}</td>
                  <td>
                    {k.status === 'active' && (confirm === k.id ? (
                      <span className="hstack">
                        <span>Revoke {k.name}? Anything using it stops working.</span>
                        <button type="button" disabled={busy} onClick={() => void revoke(k.id)} data-testid="revoke-confirm">Yes, revoke</button>
                        <button type="button" className="outline" onClick={() => setConfirm(null)}>Keep it</button>
                      </span>
                    ) : <button type="button" className="outline small" onClick={() => setConfirm(k.id)} aria-label={`Revoke key ${k.name}`} data-testid="revoke">Revoke</button>)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Audit ──────────────────────────────────────────────────────────────────
function AuditBody({ session, refresh }: { session: PreviewSession; refresh: number }) {
  const { request } = session
  const [limit, setLimit] = useState(50)
  const [load, setLoad] = useState<Load<AuditRow[]>>({ s: 'loading' })
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    let dead = false
    setLoad({ s: 'loading' })
    platformCall(request, 'GET', `/platform/audit?limit=${limit}&offset=0`).then((r) => {
      if (dead) return
      const v = ok(r) ? readAudit(r.json) : null
      setLoad(v ? { s: 'ok', v } : { s: 'error', m: ok(r) ? 'The preview answered with something that is not an audit list.' : platformError(r.status, r.json) })
    }, (e) => { if (!dead) setLoad({ s: 'error', m: msg(e, 'Could not reach the preview app') }) })
    return () => { dead = true }
  }, [request, limit, refresh, retry])

  if (load.s === 'loading') return <p role="status" className="empty-state">Loading audit…</p>
  if (load.s === 'error') return <div role="alert" data-variant="danger" className="bh-alert" data-testid="audit-error">{load.m} <button type="button" className="small" onClick={() => setRetry((n) => n + 1)}>Try again</button></div>
  if (load.v.length === 0) return <p className="empty-state" data-testid="audit-empty">Nothing recorded yet.</p>
  return (
    <>
      <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Audit table">
        <table className="stage-table" data-testid="audit-table">
          <caption className="sr-only">Recent API platform activity</caption>
          <thead><tr><th scope="col">When</th><th scope="col">Who</th><th scope="col">Action</th><th scope="col">Target</th><th scope="col">Detail</th></tr></thead>
          <tbody>
            {load.v.map((a) => (
              <tr key={a.id} data-testid="audit-row"><td>{shortWhen(a.at)}</td><td>{a.actor}</td><td>{a.action}</td><td>{a.target ?? ''}</td><td><small>{auditDetail(a.detail)}</small></td></tr>
            ))}
          </tbody>
        </table>
      </div>
      {load.v.length >= limit && limit < 200 && <button type="button" className="outline" onClick={() => setLimit((n) => Math.min(200, n + 50))} data-testid="audit-more">Show more</button>}
    </>
  )
}

function Body({ projectId, session }: { projectId: string; session: PreviewSession }) {
  const role = useMyRole(projectId)
  const [refresh, setRefresh] = useState(0)
  return (
    <>
      <SettingsPanel projectId={projectId} readOnly={role === 'viewer'} />
      <section aria-labelledby="apikeys-keys-h" data-testid="apikeys-keys">
        <h2 id="apikeys-keys-h">Keys</h2>
        <PreviewSessionGate session={session} prefix="apikeys">
          <KeysBody session={session} onChanged={() => setRefresh((n) => n + 1)} />
        </PreviewSessionGate>
      </section>
      <section aria-labelledby="apikeys-audit-h" data-testid="apikeys-audit">
        <h2 id="apikeys-audit-h">Audit</h2>
        {session.status === 'ready' ? <AuditBody session={session} refresh={refresh} /> : <p className="muted">Connect to the preview under Keys to see recent activity.</p>}
      </section>
    </>
  )
}

/** Connect > API keys: the api_platform settings block (builder), then keys and the audit log of the running project (preview session).
 *  A created key is shown once in component state and dropped on dismiss, unmount and project change (the body is keyed by project). */
export function ApiKeysPage({ projectId, session }: { projectId: string; session?: PreviewSession }) {
  const own = usePreviewSession(projectId, { disabled: !!session })
  const s = session ?? own
  return (
    <div className="stack" data-testid="apikeys-page">
      <div className="page-header">
        <div>
          <h1>API keys</h1>
          <p>Let customers read selected data through a public API with scoped, expiring keys. Choose what is shared, issue keys to the running project and review what happened.</p>
        </div>
      </div>
      <Body key={projectId} projectId={projectId} session={s} />
    </div>
  )
}
