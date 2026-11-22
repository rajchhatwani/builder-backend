import { useEffect, useState } from 'react'
import { PreviewSessionGate } from '../preview/PreviewSessionGate'
import type { PreviewSession } from '../preview/previewSession'
import { usePreviewSession } from '../preview/usePreviewSession'
import { SecretPanel } from '../apikeys/SecretPanel'
import { ok, platformCall, platformError, readApps, readInstalled, shortWhen, type AppItem, type Installed } from '../apikeys/platformLogic'

const msg = (e: unknown, f: string) => (e instanceof Error ? e.message : f)
type Load = { s: 'loading' } | { s: 'error'; m: string } | { s: 'ok'; v: AppItem[] }

function AppsBody({ session }: { session: PreviewSession }) {
  const { request } = session
  const [load, setLoad] = useState<Load>({ s: 'loading' })
  const [retry, setRetry] = useState(0)
  const [picked, setPicked] = useState<Record<string, string[]>>({}) // app name -> scopes chosen for the install
  const [busy, setBusy] = useState('')
  const [confirm, setConfirm] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [note, setNote] = useState('')
  const [secret, setSecret] = useState<Installed | null>(null)

  const fetchApps = async (): Promise<Load> => {
    const r = await platformCall(request, 'GET', '/platform/apps')
    const v = ok(r) ? readApps(r.json) : null
    return v ? { s: 'ok', v } : { s: 'error', m: ok(r) ? 'The preview answered with something that is not an app list. Generate and restart the preview after enabling the platform.' : platformError(r.status, r.json) }
  }

  useEffect(() => {
    let dead = false
    setLoad({ s: 'loading' })
    fetchApps().then((l) => { if (!dead) setLoad(l) }, (e) => { if (!dead) setLoad({ s: 'error', m: msg(e, 'Could not reach the preview app') }) })
    return () => { dead = true }
  }, [request, retry])

  const chosen = (a: AppItem) => picked[a.name] ?? a.scopes
  const toggle = (a: AppItem, s: string) => setPicked((p) => { const cur = p[a.name] ?? a.scopes; return { ...p, [a.name]: cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s] } })

  async function install(a: AppItem) {
    const scopes = chosen(a)
    if (scopes.length === 0) { setError('Pick at least one entity for the app to read.'); return }
    setBusy(a.name); setError(''); setNote('')
    try {
      const r = await platformCall(request, 'POST', `/platform/apps/${encodeURIComponent(a.name)}/install`, { scopes })
      if (!ok(r)) { setError(platformError(r.status, r.json)); return }
      const made = readInstalled(r.json)
      if (!made) setError('The preview answered with something unexpected. The app may be installed: check the list.')
      else setSecret(made)
      setLoad(await fetchApps())
    } catch (e) { setError(msg(e, 'Could not reach the preview app')) } finally { setBusy('') }
  }

  async function uninstall(a: AppItem) {
    setBusy(a.name); setError(''); setNote('')
    try {
      const r = await platformCall(request, 'POST', `/platform/apps/${encodeURIComponent(a.name)}/uninstall`)
      if (!ok(r)) { setError(platformError(r.status, r.json)); return }
      setConfirm(null)
      setNote(`${a.title} uninstalled.`)
      setLoad(await fetchApps())
    } catch (e) { setError(msg(e, 'Could not reach the preview app')) } finally { setBusy('') }
  }

  if (load.s === 'loading') return <p role="status" className="empty-state">Loading apps…</p>
  if (load.s === 'error') return <div role="alert" data-variant="danger" className="bh-alert" data-testid="apps-error">{load.m} <button type="button" className="small" onClick={() => setRetry((n) => n + 1)}>Try again</button></div>
  return (
    <div className="stack">
      {secret && (
        <SecretPanel
          title={`App "${secret.app}" installed`}
          note="Copy the token and the signing secret now. They are shown only once and cannot be shown again."
          secrets={[{ label: 'App token', value: secret.token }, { label: 'Signing secret', value: secret.signing_secret }]}
          onDismiss={() => setSecret(null)}
        />
      )}
      {error && <div role="alert" data-variant="danger" className="bh-alert" data-testid="apps-action-error">{error}</div>}
      <p role="status" aria-live="polite">{note && <small data-testid="apps-note">{note}</small>}</p>
      {load.v.length === 0 && <p className="empty-state" data-testid="apps-empty">No apps are defined. Add some under Connect, API keys, Settings.</p>}
      <ul className="stack" style={{ listStyle: 'none', padding: 0 }}>
        {load.v.map((a) => (
          <li key={a.name} data-testid="app-item" data-installed={a.installed}>
            <h3>{a.title}</h3>
            <p className="muted"><code>{a.name}</code>{a.events.length > 0 && <> · events: {a.events.join(', ')}</>}</p>
            <p data-testid="app-status"><span aria-hidden="true">{a.installed ? '✓ ' : '– '}</span>{a.installed ? `Installed${a.installed_at ? ` ${shortWhen(a.installed_at)}` : ''}; reads ${a.granted_scopes.join(', ') || 'nothing'}` : 'Not installed'}</p>
            {!a.installed && (
              <fieldset>
                <legend>Entities to let {a.title} read</legend>
                {a.scopes.map((s) => (
                  <label key={s}><input type="checkbox" checked={chosen(a).includes(s)} onChange={() => toggle(a, s)} data-testid="app-scope" /> {s}</label>
                ))}
              </fieldset>
            )}
            {!a.installed && <button type="button" disabled={!!busy} onClick={() => void install(a)} data-testid="install" aria-label={`Install ${a.title}`}>{busy === a.name ? 'Working…' : 'Install'}</button>}
            {a.installed && (confirm === a.name ? (
              <span className="hstack">
                <span>Uninstall {a.title}? Its token stops working.</span>
                <button type="button" disabled={!!busy} onClick={() => void uninstall(a)} data-testid="uninstall-confirm">Yes, uninstall</button>
                <button type="button" className="outline" onClick={() => setConfirm(null)}>Keep it</button>
              </span>
            ) : <button type="button" className="outline" onClick={() => setConfirm(a.name)} data-testid="uninstall" aria-label={`Uninstall ${a.title}`}>Uninstall</button>)}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Connect > Apps: apps a tenant can install from the running project. The one-time token and signing secret live in component state only
 *  (dropped on dismiss, unmount and project change). */
export function AppsPage({ projectId, session }: { projectId: string; session?: PreviewSession }) {
  const own = usePreviewSession(projectId, { disabled: !!session })
  const s = session ?? own
  return (
    <section aria-labelledby="apps-h" data-testid="apps-page" className="stack">
      <h1 id="apps-h">Apps</h1>
      <p className="muted">Apps a tenant can install into the running project, each limited to the entities you chose. Installing gives the app a token and a signing secret, shown once.</p>
      <h2>Available apps</h2>
      <PreviewSessionGate session={s} prefix="apps">
        <AppsBody key={projectId} session={s} />
      </PreviewSessionGate>
    </section>
  )
}
