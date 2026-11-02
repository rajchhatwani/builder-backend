import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, api } from '../../api/client'
import {
  CELL_TEXT, EXAMPLE_DELIVERIES, EXAMPLE_TYPES, checkTemplate, maskAddress, preferenceMatrix, readNotifications,
  renderPreview, renderSubject, sampleValues, tplKey, type NBlock, type NTemplate, type NType,
} from './notificationsLogic'

type Load = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; block: NBlock; raw: Raw; version: number }
type Raw = Record<string, unknown> | null
type Tab = 'templates' | 'preferences' | 'deliveries'
const TABS: { id: Tab; label: string }[] = [
  { id: 'templates', label: 'Templates' },
  { id: 'preferences', label: 'Preferences' },
  { id: 'deliveries', label: 'Delivery log' },
]
const HAS_SUBJECT = new Set(['email', 'push'])

/** Connect > Notifications. The types and channels come from the spec's `notifications` block (GET /behavior/notifications);
 *  "Save template" writes the block back with PUT /behavior/notifications and the section version (409 = someone else saved). */
export function NotificationsPage({ projectId }: { projectId: string }) {
  const [load, setLoad] = useState<Load>({ status: 'loading' })
  const [tab, setTab] = useState<Tab>('templates')
  const [example, setExample] = useState(false)

  const reload = useCallback(async () => {
    setLoad({ status: 'loading' })
    try {
      const r = await api.getBlock(projectId, 'notifications')
      const raw = (r.notifications as Raw) ?? null
      setLoad({ status: 'ready', block: readNotifications({ notifications: raw }), raw, version: typeof r.version === 'number' ? r.version : 0 })
    } catch (err) {
      setLoad({ status: 'error', message: err instanceof Error ? err.message : 'Could not load the spec' })
    }
  }, [projectId])
  useEffect(() => { void reload() }, [reload])

  const header = (
    <div className="page-header">
      <div>
        <h1>Notifications</h1>
        <p>Email, SMS and push messages your generated app sends: one template per type and channel, who can opt out, and what was delivered.</p>
      </div>
    </div>
  )
  if (load.status === 'loading') return <>{header}<p className="empty-state" role="status">Loading notifications…</p></>
  if (load.status === 'error') {
    return (
      <>
        {header}
        <div role="alert" data-variant="danger" className="bh-alert" data-testid="notif-error">
          Could not load notifications: {load.message} <button className="small" onClick={() => void reload()}>Try again</button>
        </div>
      </>
    )
  }

  async function saveTemplate(typeName: string, tpl: NTemplate) {
    if (load.status !== 'ready') throw new Error('The page is still loading.')
    if (example && load.block.types.length === 0) throw new Error('This is an example: nothing is saved.')
    const raw = load.raw ?? {}
    const list = Array.isArray(raw.types) ? (raw.types as Record<string, unknown>[]) : []
    const types = list.map((t) => {
      if (t.name !== typeName) return t
      const templates = Array.isArray(t.templates) ? (t.templates as Record<string, unknown>[]) : []
      const entry = { channel: tpl.channel, subject: tpl.subject, body: tpl.body, html: tpl.html }
      const has = templates.some((x) => x.channel === tpl.channel)
      return { ...t, templates: has ? templates.map((x) => (x.channel === tpl.channel ? { ...x, ...entry } : x)) : [...templates, entry] }
    })
    const r = await api.putBlock(projectId, 'notifications', { notifications: { ...raw, types }, expected_version: load.version })
    const next = (r.notifications as Raw) ?? null
    setLoad({ status: 'ready', block: readNotifications({ notifications: next }), raw: next, version: typeof r.version === 'number' ? r.version : load.version + 1 })
  }

  const types = example && load.block.types.length === 0 ? EXAMPLE_TYPES : load.block.types
  return (
    <>
      {header}
      <p className="muted" data-testid="notif-note">
        Templates are saved to the project spec. Preferences and the delivery log live in the generated app.
      </p>
      {types.length === 0 ? (
        <div className="empty-state" data-testid="notif-empty">
          <p>This spec declares no notification types{load.block.enabled ? '' : ' (notifications are off)'}.</p>
          <button onClick={() => setExample(true)}>Try with an example</button>
        </div>
      ) : (
        <>
          {example && load.block.types.length === 0 && <p role="status" data-testid="notif-example">Showing an example. Nothing here comes from your spec.</p>}
          <nav aria-label="Notification views" className="bh-tabs">
            {TABS.map((t) => (
              <button key={t.id} className={t.id === tab ? '' : 'outline'} aria-pressed={t.id === tab} onClick={() => setTab(t.id)}>{t.label}</button>
            ))}
          </nav>
          {tab === 'templates' && <Templates key={example ? 'ex' : 'spec'} types={types} onSave={(t, tpl) => saveTemplate(t, tpl)} />}
          {tab === 'preferences' && <Preferences types={types} />}
          {tab === 'deliveries' && <Deliveries example={example && load.block.types.length === 0} />}
        </>
      )}
    </>
  )
}

function Templates({ types, onSave }: { types: NType[]; onSave: (typeName: string, tpl: NTemplate) => Promise<void> }) {
  const [typeName, setTypeName] = useState(types[0].name)
  const type = types.find((t) => t.name === typeName) ?? types[0]
  const [channel, setChannel] = useState(type.channels[0] ?? '')
  const ch = type.channels.includes(channel) ? channel : (type.channels[0] ?? '')
  const key = tplKey(type.name, ch)
  const base: NTemplate = type.templates.find((t) => t.channel === ch) ?? { channel: ch, subject: '', body: '', html: false }
  const saved = base
  const [edit, setEdit] = useState<NTemplate>(saved)
  const [saving, setSaving] = useState(false)
  const [conflict, setConflict] = useState(false)
  const [note, setNote] = useState('')
  const [err, setErr] = useState('')
  useEffect(() => { setEdit(base); setNote(''); setErr(''); setConflict(false) }, [key])

  const dirty = edit.body !== saved.body || edit.subject !== saved.subject || edit.html !== saved.html
  const subjectCheck = checkTemplate(edit.subject, type.variables)
  const bodyCheck = checkTemplate(edit.body, type.variables)
  const problems = [
    ...(edit.body.trim() ? [] : ['The body cannot be empty.']),
    ...[...new Set([...subjectCheck.unknown, ...bodyCheck.unknown])].map((n) => `{{ ${n} }} is not a declared variable.`),
    ...(subjectCheck.malformed || bodyCheck.malformed ? ['Only {{ name }} placeholders are allowed: no expressions, filters or stray braces.'] : []),
  ]
  const values = useMemo(() => sampleValues(type.variables), [type.variables])
  const subjectOn = HAS_SUBJECT.has(ch)

  async function save() {
    if (problems.length) { setErr('Fix the problems above before saving.'); setNote(''); return }
    setSaving(true); setErr(''); setNote(''); setConflict(false)
    try {
      await onSave(type.name, { ...edit, channel: ch })
      setNote(`Saved the ${type.name} / ${ch} template.`)
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setConflict(true)
      else setErr(e instanceof Error ? e.message : 'Could not save')
    } finally { setSaving(false) }
  }

  return (
    <section aria-labelledby="nt-templates">
      <h2 id="nt-templates">Template editor</h2>
      <div className="bh-grid">
        <div className="bh-field">
          <label htmlFor="nt-type">Notification type</label>
          <select id="nt-type" value={type.name} onChange={(e) => { setTypeName(e.target.value); setChannel('') }}>
            {types.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
          </select>
          <small className="muted">{type.category === 'transactional' ? 'Transactional: always sent' : 'Optional: users can opt out'}</small>
        </div>
        <div className="bh-field">
          <label htmlFor="nt-channel">Channel</label>
          <select id="nt-channel" value={ch} onChange={(e) => setChannel(e.target.value)} disabled={type.channels.length === 0}>
            {type.channels.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
      </div>
      {type.channels.length === 0 ? <p className="empty-state">This type declares no channels.</p> : (
        <>
          <p>
            Declared variables:{' '}
            {type.variables.length === 0 ? <span className="muted">none</span> : (
              <span data-testid="nt-variables">{type.variables.map((v) => <code key={v} className="nt-var">{`{{ ${v} }}`}</code>)}</span>
            )}
          </p>
          {subjectOn && (
            <div className="bh-field">
              <label htmlFor="nt-subject">{ch === 'push' ? 'Title' : 'Subject'}</label>
              <input id="nt-subject" value={edit.subject} maxLength={200} onChange={(e) => setEdit({ ...edit, subject: e.target.value })} />
            </div>
          )}
          <div className="bh-field">
            <label htmlFor="nt-body">Message body</label>
            <textarea id="nt-body" rows={6} value={edit.body} aria-invalid={problems.length > 0 || undefined}
              aria-describedby={problems.length ? 'nt-problems' : undefined} onChange={(e) => setEdit({ ...edit, body: e.target.value })} />
          </div>
          {ch === 'email' && (
            <div className="bh-field">
              <label><input type="checkbox" checked={edit.html} onChange={(e) => setEdit({ ...edit, html: e.target.checked })} /> HTML body (values are escaped)</label>
            </div>
          )}
          {problems.length > 0 && (
            <ul id="nt-problems" className="bh-error" data-testid="nt-problems">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
          )}
          <div className="bh-savebar">
            <button onClick={() => void save()} disabled={!dirty || saving}>{saving ? 'Saving…' : 'Save template'}</button>
            <button className="outline" onClick={() => setEdit(saved)} disabled={!dirty}>Discard changes</button>
            {dirty && <small className="muted">Unsaved changes</small>}
            <span role="status" aria-live="polite">{note && <small data-testid="nt-saved">{note}</small>}</span>
            {conflict && (
              <div role="alert" data-variant="warning" className="bh-conflict" data-testid="conflict">
                Someone else changed the notifications since you opened this page, so your save was not applied. Reload the page to see their version.
              </div>
            )}
            {err && <div role="alert" data-variant="danger" className="bh-alert">{err}</div>}
          </div>
          <h2 id="nt-preview-h">Preview</h2>
          <p className="muted">Sample data, filled in here in your browser and shown as plain text. The real message is rendered by the generated app.</p>
          <div className="nt-preview" role="region" aria-labelledby="nt-preview-h" data-testid="nt-preview">
            {subjectOn && <p><strong>{ch === 'push' ? 'Title' : 'Subject'}:</strong> <span data-testid="nt-preview-subject">{renderSubject(edit.subject, values)}</span></p>}
            <pre data-testid="nt-preview-body">{renderPreview(edit.body, values, edit.html && ch === 'email')}</pre>
          </div>
          <details>
            <summary>Sample values used</summary>
            <ul>{type.variables.map((v) => <li key={v}><code>{v}</code>: {values[v]}</li>)}</ul>
          </details>
        </>
      )}
    </section>
  )
}

function Preferences({ types }: { types: NType[] }) {
  const { channels, rows } = preferenceMatrix(types)
  return (
    <section aria-labelledby="nt-prefs">
      <h2 id="nt-prefs">Preferences matrix</h2>
      <p className="muted">The defaults from the spec. Each user of the generated app can change optional cells for themselves; transactional types stay on.</p>
      {channels.length === 0 ? <p className="empty-state">No channel is declared.</p> : (
        <div className="nt-scroll" tabIndex={0} role="region" aria-label="Matrix of types by channel">
          <table data-testid="nt-matrix">
            <caption className="sr-only">Notification types by channel</caption>
            <thead><tr><th scope="col">Type</th>{channels.map((c) => <th key={c} scope="col">{c}</th>)}</tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.type.name}>
                  <th scope="row">{r.type.name} <small className="muted">{r.type.category}</small></th>
                  {r.cells.map((c) => (
                    <td key={c.channel} data-state={c.state}>
                      <span aria-hidden="true">{c.state === 'locked-on' ? '🔒 ' : ''}</span>{CELL_TEXT[c.state]}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function Deliveries({ example }: { example: boolean }) {
  const rows = example ? EXAMPLE_DELIVERIES : []
  return (
    <section aria-labelledby="nt-log">
      <h2 id="nt-log">Delivery log</h2>
      <p className="muted">Read-only. Addresses are masked. Message bodies and variables are not kept after delivery.</p>
      {rows.length === 0 ? (
        <p className="empty-state" data-testid="nt-log-empty">
          The delivery log lives in the generated app (GET /notifications/deliveries, admin role) and cannot be reached from the builder. Open it in your running app.
        </p>
      ) : (
        <div className="nt-scroll" tabIndex={0} role="region" aria-label="Table of deliveries">
          <table data-testid="nt-log">
            <caption className="sr-only">Example deliveries</caption>
            <thead><tr><th scope="col">When</th><th scope="col">Type</th><th scope="col">Channel</th><th scope="col">To</th><th scope="col">Status</th><th scope="col">Attempts</th></tr></thead>
            <tbody>
              {rows.map((d) => (
                <tr key={d.id}>
                  <td><time dateTime={d.at}>{d.at.slice(0, 16).replace('T', ' ')}</time></td>
                  <td>{d.type}</td><td>{d.channel}</td><td>{maskAddress(d.to)}</td><td>{d.status}</td><td>{d.attempts}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
