import { useEffect, useRef, useState } from 'react'
import { useUi } from '../../components/Ui'
import { Scroll } from './BlockUi'
import { MAX_SECRET_SHOWN_MS } from './blockLogic'
import { webhookApi, type Conn, type InboundEndpoint, type Subscription } from './webhookApi'

interface Shown { label: string; secret: string }

/** Live webhook subscriptions of the GENERATED API (needs the preview API origin and an admin bearer token).
 *  The token and any secret live in React state only. A secret is shown once, then cleared (on dismiss, after
 *  MAX_SECRET_SHOWN_MS, or when leaving the page). Nothing is written to storage, the URL or the console. */
export function WebhookSubscriptions({ origin, events, inbound }: { origin: string; events: string[]; inbound: string[] }) {
  const { confirm } = useUi()
  const [token, setToken] = useState('')
  const [conn, setConn] = useState<Conn | null>(null)
  const [subs, setSubs] = useState<Subscription[] | null>(null)
  const [endpoints, setEndpoints] = useState<InboundEndpoint[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [shown, setShown] = useState<Shown | null>(null)
  const [url, setUrl] = useState('')
  const [desc, setDesc] = useState('')
  const [picked, setPicked] = useState<string[]>([])
  const [inName, setInName] = useState(inbound[0] ?? '')
  const [inValue, setInValue] = useState('')
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const secretRef = useRef<HTMLDivElement>(null)

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])
  useEffect(() => { if (shown) secretRef.current?.focus() }, [shown])

  function reveal(label: string, secret: string) {
    if (timer.current) clearTimeout(timer.current)
    setShown({ label, secret })
    timer.current = setTimeout(() => setShown(null), MAX_SECRET_SHOWN_MS)
  }
  function dismiss() {
    if (timer.current) clearTimeout(timer.current)
    setShown(null)
  }
  async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(true)
    setError('')
    try {
      return await fn()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The request failed')
      return undefined
    } finally {
      setBusy(false)
    }
  }
  async function connect() {
    const c = { origin, token: token.trim() }
    if (!c.token) return
    const list = await run(async () => {
      const [s, i] = await Promise.all([webhookApi.list(c), webhookApi.inbound(c).catch(() => [] as InboundEndpoint[])])
      setEndpoints(i)
      return s
    })
    if (list) {
      setConn(c)
      setSubs(list)
      setToken('') // the typed copy leaves the input; only `conn` (in memory) keeps it for the calls
    }
  }
  const refresh = async (c: Conn) => setSubs(await webhookApi.list(c))

  /** Show the one-time secret FIRST; a failed list refresh afterwards must never lose it. */
  async function refreshQuietly(c: Conn) {
    try {
      await refresh(c)
    } catch {
      setError('Saved, but the list could not be refreshed. Reload the subscriptions to see the change.')
    }
  }
  async function create() {
    if (!conn) return
    const made = await run(() => webhookApi.create(conn, { url: url.trim(), event_types: picked, description: desc.trim() }))
    if (made) {
      reveal(`Signing secret for ${made.url}`, made.secret)
      setUrl('')
      setDesc('')
      setPicked([])
      await refreshQuietly(conn)
    }
  }
  async function rotate(s: Subscription) {
    if (!conn) return
    const ok = await confirm({
      title: 'Rotate the signing secret?',
      message: `A new secret is created for ${s.url}. You see it once. The old one keeps working for the overlap window, so update the receiver before then.`,
      confirmLabel: 'Rotate',
    })
    if (!ok) return
    const r = await run(() => webhookApi.rotate(conn, s.id))
    if (r) {
      reveal(`New signing secret for ${s.url} (version ${r.secret_version})`, r.secret)
      await refreshQuietly(conn)
    }
  }
  async function toggle(s: Subscription) {
    if (!conn) return
    await run(async () => {
      await webhookApi.setEnabled(conn, s.id, s.status !== 'active')
      await refresh(conn)
    })
  }
  async function remove(s: Subscription) {
    if (!conn) return
    const ok = await confirm({ title: 'Delete this subscription?', message: `${s.url} stops receiving events. Its delivery log is removed.`, confirmLabel: 'Delete', danger: true })
    if (!ok) return
    await run(async () => {
      await webhookApi.remove(conn, s.id)
      await refresh(conn)
    })
  }
  async function setInbound() {
    if (!conn || !inName || !inValue) return
    const value = inValue
    setInValue('') // the typed secret leaves the page at once
    const r = await run(async () => {
      const out = await webhookApi.setInboundSecret(conn, inName, value)
      setEndpoints(await webhookApi.inbound(conn))
      return out
    })
    if (r) setError('')
  }
  const toggleEvent = (e: string) => setPicked((p) => (p.includes(e) ? p.filter((x) => x !== e) : [...p, e]))

  return (
    <section aria-labelledby="wh-live" data-testid="wh-live">
      <h2 id="wh-live">Subscriptions (generated API)</h2>
      <p className="muted">
        These call the running generated project at <code>{origin}</code> as its admin. The token stays in this page's memory
        only and is forgotten when you leave.
      </p>
      {!conn && (
        <form className="bh-actions" onSubmit={(e) => { e.preventDefault(); void connect() }}>
          <div className="bh-field">
            <label htmlFor="wh-token">Admin bearer token</label>
            <input id="wh-token" type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} />
          </div>
          <button type="submit" disabled={busy || !token.trim()}>{busy ? 'Connecting…' : 'Load subscriptions'}</button>
        </form>
      )}
      {error && <div role="alert" data-variant="danger" className="bh-alert" data-testid="wh-error">{error}</div>}
      {shown && (
        <div ref={secretRef} tabIndex={-1} role="alert" data-variant="warning" className="card co-secret" data-testid="wh-secret">
          <strong>{shown.label}</strong>
          <p>Copy it now. It is shown only once and cannot be read again.</p>
          <code data-testid="wh-secret-value">{shown.secret}</code>
          <div className="bh-actions">
            <button className="small" onClick={() => void navigator.clipboard?.writeText(shown.secret).catch(() => undefined)}>Copy</button>
            <button className="small outline" onClick={dismiss}>I have stored it</button>
          </div>
        </div>
      )}
      {conn && subs && (
        <>
          {subs.length === 0 ? (
            <p className="muted" data-testid="wh-none">No subscriptions yet.</p>
          ) : (
            <Scroll label="Webhook subscriptions"><table className="bh-items" data-testid="wh-table">
              <caption>Webhook subscriptions</caption>
              <thead>
                <tr><th scope="col">URL</th><th scope="col">Events</th><th scope="col">Status</th><th scope="col">Secret</th><th scope="col"><span className="sr-only">Actions</span></th></tr>
              </thead>
              <tbody>
                {subs.map((s) => (
                  <tr key={s.id}>
                    <td>{s.url}</td>
                    <td>{s.event_types.join(', ')}</td>
                    <td>{s.status}{s.disabled_reason ? ` (${s.disabled_reason})` : ''}{s.consecutive_failures ? `, ${s.consecutive_failures} failures` : ''}</td>
                    <td>version {s.secret_version}{s.rotating ? ', rotating' : ''}</td>
                    <td className="bh-actions">
                      <button className="small outline" disabled={busy} onClick={() => void rotate(s)} aria-label={`Rotate the secret of ${s.url}`}>Rotate secret</button>
                      <button className="small outline" disabled={busy} onClick={() => void toggle(s)} aria-label={`${s.status === 'active' ? 'Disable' : 'Enable'} ${s.url}`}>{s.status === 'active' ? 'Disable' : 'Enable'}</button>
                      <button className="small outline" disabled={busy} onClick={() => void remove(s)} aria-label={`Delete ${s.url}`}>Delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table></Scroll>
          )}
          <form className="card bh-row" onSubmit={(e) => { e.preventDefault(); void create() }}>
            <h3>New subscription</h3>
            <div className="bh-grid">
              <div className="bh-field">
                <label htmlFor="wh-url">Receiver URL</label>
                <input id="wh-url" type="url" value={url} onChange={(e) => setUrl(e.target.value)} required />
              </div>
              <div className="bh-field">
                <label htmlFor="wh-desc">Description</label>
                <input id="wh-desc" value={desc} maxLength={200} onChange={(e) => setDesc(e.target.value)} />
              </div>
            </div>
            <fieldset>
              <legend>Events</legend>
              {events.length === 0 && <p className="muted">The spec lists no subscribable events.</p>}
              {events.map((e) => (
                <label key={e} className="bh-check"><input type="checkbox" checked={picked.includes(e)} onChange={() => toggleEvent(e)} /> {e}</label>
              ))}
            </fieldset>
            <button type="submit" disabled={busy || !url.trim() || picked.length === 0}>Create subscription</button>
          </form>
          {inbound.length > 0 && (
            <form className="card bh-row" onSubmit={(e) => { e.preventDefault(); void setInbound() }}>
              <h3>Incoming receivers</h3>
              <ul>
                {inbound.map((n) => {
                  const e = endpoints.find((x) => x.name === n)
                  return <li key={n}><code>{n}</code>: {e?.has_secret ? `secret version ${e.secret_version}${e.rotating ? ', rotating' : ''}` : 'no secret stored yet'}</li>
                })}
              </ul>
              <div className="bh-grid">
                <div className="bh-field">
                  <label htmlFor="wh-in-name">Receiver</label>
                  <select id="wh-in-name" value={inName} onChange={(e) => setInName(e.target.value)}>
                    {inbound.map((n) => <option key={n}>{n}</option>)}
                  </select>
                </div>
                <div className="bh-field">
                  <label htmlFor="wh-in-value">Sender's signing secret (16 characters or more)</label>
                  <input id="wh-in-value" type="password" autoComplete="off" minLength={16} value={inValue} onChange={(e) => setInValue(e.target.value)} />
                </div>
              </div>
              <button type="submit" disabled={busy || inValue.length < 16}>Store or rotate secret</button>
            </form>
          )}
        </>
      )}
    </section>
  )
}
