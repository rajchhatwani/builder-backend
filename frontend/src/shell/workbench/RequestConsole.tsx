import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../api/client'
import { sendRequest } from './sendRequest'
import {
  buildRequestUrl, generatePayload, parseOperations, pushHistory, redactBodyText, redactJson, redactPath,
  type HistoryEntry, type Operation,
} from './workbenchLogic'

type Roles = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; roles: { name: string; label: string }[] }
type Shown = { kind: 'live'; status: number | null; text: string; ms: number; error: string } | { kind: 'history'; entry: HistoryEntry }

/** Request console. Tokens live ONLY in this component's state (cleared on unmount); history is a React state
 *  array of redacted entries; nothing is written to any browser storage. Responses are rendered as text. */
export function RequestConsole({ projectId, origin, doc }: { projectId: string; origin: string; doc: Record<string, unknown> }) {
  const ops = useMemo(() => parseOperations(doc), [doc])
  const [opId, setOpId] = useState('')
  const op: Operation | undefined = ops.find((o) => o.id === opId) ?? ops[0]
  const [values, setValues] = useState<Record<string, string>>({})
  const [body, setBody] = useState('')
  const [role, setRole] = useState('')
  const [tokens, setTokens] = useState<Record<string, string>>({})
  const [roles, setRoles] = useState<Roles>({ status: 'loading' })
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [shown, setShown] = useState<Shown | null>(null)
  const [sending, setSending] = useState(false)
  const [formError, setFormError] = useState('')
  const seq = useRef(0)

  useEffect(() => {
    let off = false
    setRoles({ status: 'loading' })
    api.getBehaviorRoles(projectId)
      .then((r) => { if (!off) setRoles({ status: 'ready', roles: r.roles }) })
      .catch((e: unknown) => { if (!off) setRoles({ status: 'error', message: e instanceof Error ? e.message : 'Could not load roles' }) })
    return () => { off = true }
  }, [projectId])

  // switching operation resets its inputs
  useEffect(() => {
    setValues({})
    setFormError('')
    setBody(op?.bodySchema ? JSON.stringify(generatePayload(doc, op.bodySchema, 'valid'), null, 2) : '')
  }, [op?.id, doc]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!ops.length) return <p className="muted" data-testid="wb-no-ops">This API description has no endpoints yet. Add an entity and regenerate.</p>
  if (!op) return null

  const token = role ? (tokens[role] ?? '') : ''
  const fill = (mode: 'valid' | 'invalid') => op.bodySchema && setBody(JSON.stringify(generatePayload(doc, op.bodySchema, mode), null, 2))

  async function send() {
    if (!op) return
    setFormError('')
    let url: string
    try {
      url = buildRequestUrl(origin, op.path, values, op.params)
    } catch (e) {
      setFormError(e instanceof Error ? e.message : 'Invalid request')
      return
    }
    let payload: string | undefined
    if (op.bodySchema && body.trim()) {
      try { payload = JSON.stringify(JSON.parse(body)) } catch { setFormError('The body is not valid JSON'); return }
    }
    setSending(true)
    const base = { id: ++seq.current, at: new Date().toLocaleTimeString(), method: op.method.toUpperCase(), path: redactPath(new URL(url).pathname + new URL(url).search), role: role || 'anonymous', authorization: token ? ('[redacted]' as const) : ('none' as const), requestBody: payload ? JSON.stringify(redactJson(JSON.parse(payload)), null, 2) : '' }
    try {
      const r = await sendRequest({ url, origin, method: op.method.toUpperCase(), body: payload, bearer: token || undefined })
      setShown({ kind: 'live', status: r.status, text: r.text, ms: r.ms, error: '' })
      setHistory((h) => pushHistory(h, { ...base, status: r.status, ms: r.ms, responseBody: redactBodyText(r.text), error: '' }))
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Request failed'
      setShown({ kind: 'live', status: null, text: '', ms: 0, error: msg })
      setHistory((h) => pushHistory(h, { ...base, status: null, ms: 0, responseBody: '', error: msg }))
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="wb-console" data-testid="wb-console">
      <form className="wb-form" onSubmit={(e) => { e.preventDefault(); void send() }}>
        <div className="bh-grid">
          <div className="bh-field">
            <label htmlFor="wb-op">Endpoint</label>
            <select id="wb-op" value={op.id} onChange={(e) => setOpId(e.target.value)}>
              {ops.map((o) => <option key={o.id} value={o.id}>{o.id}{o.summary ? ` — ${o.summary}` : ''}</option>)}
            </select>
          </div>
          <div className="bh-field">
            <label htmlFor="wb-role">Act as role</label>
            <select id="wb-role" value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="">No role (anonymous)</option>
              {roles.status === 'ready' && roles.roles.map((r) => <option key={r.name} value={r.name}>{r.label || r.name}</option>)}
            </select>
            {roles.status === 'loading' && <small className="muted" role="status">Loading roles…</small>}
            {roles.status === 'error' && <small className="bh-error" role="alert">{roles.message}</small>}
            {roles.status === 'ready' && !roles.roles.length && <small className="muted">This project declares no roles.</small>}
          </div>
          {role && (
            <div className="bh-field">
              <label htmlFor="wb-token">Test-user token for {role}</label>
              <input id="wb-token" type="password" autoComplete="off" spellCheck={false} value={token}
                onChange={(e) => setTokens((t) => ({ ...t, [role]: e.target.value }))} />
              <small className="muted">Kept in memory only; gone when you close this page or leave the project. Never saved or shown in history.</small>
            </div>
          )}
        </div>
        {op.params.length > 0 && (
          <div className="bh-grid">
            {op.params.map((p) => (
              <div className="bh-field" key={`${p.in}:${p.name}`}>
                <label htmlFor={`wb-p-${p.name}`}>{p.name} <small className="muted">({p.in}{p.required ? ', required' : ''})</small></label>
                <input id={`wb-p-${p.name}`} value={values[p.name] ?? ''} onChange={(e) => setValues((v) => ({ ...v, [p.name]: e.target.value }))} />
              </div>
            ))}
          </div>
        )}
        {op.bodySchema && (
          <div className="bh-field">
            <label htmlFor="wb-body">JSON body</label>
            <textarea id="wb-body" rows={8} spellCheck={false} value={body} onChange={(e) => setBody(e.target.value)} />
            <div className="bh-actions">
              <button type="button" className="outline small" onClick={() => fill('valid')}>Generate valid payload</button>
              <button type="button" className="outline small" onClick={() => fill('invalid')}>Generate invalid payload</button>
            </div>
          </div>
        )}
        {formError && <div role="alert" data-variant="danger" className="bh-alert" data-testid="wb-form-error">{formError}</div>}
        <div className="bh-actions">
          <button type="submit" disabled={sending}>{sending ? 'Sending…' : 'Send request'}</button>
          <small className="muted">Goes to <code>{origin}</code> only.</small>
        </div>
      </form>

      <section aria-labelledby="wb-resp-h" className="wb-response">
        <h3 id="wb-resp-h">Response</h3>
        <div aria-live="polite" data-testid="wb-response">
          {!shown && <p className="muted">No request sent yet.</p>}
          {shown?.kind === 'live' && (shown.error
            ? <div role="alert" data-variant="danger" className="bh-alert">{shown.error}</div>
            : <><p><strong data-testid="wb-status">{shown.status}</strong> <small className="muted">{shown.ms} ms</small></p><pre className="wb-pre" tabIndex={0} data-testid="wb-response-body">{shown.text}</pre></>)}
          {shown?.kind === 'history' && (
            <><p><strong>{shown.entry.status ?? 'error'}</strong> <small className="muted">{shown.entry.method} {shown.entry.path} as {shown.entry.role} (saved copy, secrets redacted)</small></p>
              {shown.entry.requestBody && <pre className="wb-pre" tabIndex={0}>{shown.entry.requestBody}</pre>}
              <pre className="wb-pre" tabIndex={0}>{shown.entry.error || shown.entry.responseBody}</pre></>)}
        </div>
      </section>

      <section aria-labelledby="wb-hist-h" className="wb-history">
        <h3 id="wb-hist-h">History <small className="muted">(this tab only, secrets redacted)</small></h3>
        {!history.length ? <p className="muted" data-testid="wb-history-empty">Requests you send appear here.</p> : (
          <>
            <ul data-testid="wb-history">
              {history.map((h) => (
                <li key={h.id}>
                  <button type="button" className="ghost small" onClick={() => setShown({ kind: 'history', entry: h })}>
                    {h.at} {h.method} {h.path} as {h.role}: {h.status ?? 'failed'}
                  </button>
                </li>
              ))}
            </ul>
            <button type="button" className="outline small" onClick={() => { setHistory([]); setShown(null) }}>Clear history</button>
          </>
        )}
      </section>
    </div>
  )
}
