import { useCallback, useEffect, useId, useState } from 'react'
import { api } from '../../api/client'
import type { AuthConfig, KeycloakConfig, SuiteRef, ValidationIssue } from '../../api/types'
import { link } from '../../components/Sidebar'
import {
  EMPTY_FORM, JOIN_STATES, MAX_SUITE_ID_LENGTH, formFromSuite, hasHints, hints, isDirty, keycloakBodyForSuite, patchBody, suiteIssues, suiteRealm,
  type SuiteForm,
} from './suiteLogic'
import type { SuiteJoinState } from '../../api/types'

type Load = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; auth: AuthConfig; keycloak: KeycloakConfig }

const msg = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback)

export function SuitePage({ projectId }: { projectId: string }) {
  const [load, setLoad] = useState<Load>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  const [form, setForm] = useState<SuiteForm>(EMPTY_FORM)
  const [saved, setSaved] = useState<SuiteRef | null>(null)
  const [provider, setProvider] = useState<string>('builtin')
  const [issues, setIssues] = useState<ValidationIssue[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [confirmRemove, setConfirmRemove] = useState(false)
  const ids = { enabled: useId(), suiteId: useId(), hub: useId(), join: useId() }

  const refreshIssues = useCallback(async () => {
    try {
      setIssues(suiteIssues((await api.validateProject(projectId)).issues))
    } catch {
      setIssues([])
    }
  }, [projectId])

  useEffect(() => {
    let cancelled = false
    setLoad({ status: 'loading' })
    Promise.all([api.getAuthConfig(projectId), api.getKeycloak(projectId)])
      .then(([auth, keycloak]) => {
        if (cancelled) return
        setForm(formFromSuite(auth.suite))
        setSaved(auth.suite)
        setProvider(auth.provider)
        setLoad({ status: 'ready', auth, keycloak })
        void refreshIssues()
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoad({ status: 'error', message: msg(err, 'Could not load the sign-in settings') })
      })
    return () => {
      cancelled = true
    }
  }, [projectId, attempt, refreshIssues])

  const set = (patch: Partial<SuiteForm>) => {
    setForm((f) => ({ ...f, ...patch }))
    setNote(null)
  }

  const save = async (remove: boolean) => {
    if (load.status !== 'ready') return
    const next = remove ? { ...EMPTY_FORM } : form
    setBusy(true)
    setError(null)
    setNote(null)
    try {
      const auth = await api.updateAuthConfig(projectId, patchBody(next))
      let keycloak = load.keycloak
      if (!remove) keycloak = await api.putKeycloak(projectId, keycloakBodyForSuite(load.keycloak, next.suiteId))
      setLoad({ status: 'ready', auth, keycloak })
      setSaved(auth.suite)
      setForm(formFromSuite(auth.suite))
      setProvider(auth.provider)
      setConfirmRemove(false)
      setNote(remove ? 'This project is no longer part of a suite.' : 'Saved.')
      await refreshIssues()
    } catch (err) {
      setError(msg(err, 'Could not save'))
    } finally {
      setBusy(false)
    }
  }

  const h = hints(form)
  const notKeycloak = provider !== 'keycloak'
  const dirty = isDirty(form, saved)

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Suite identity</h1>
          <p>Let several apps share one sign-in. Each app keeps its own roles and permissions; people sign in once at the shared hub.</p>
        </div>
      </div>
      {load.status === 'loading' && <p className="empty-state">Loading…</p>}
      {load.status === 'error' && (
        <div className="card empty-hero" role="alert">
          <h2>We could not load this page</h2>
          <p>{load.message}</p>
          <button onClick={() => setAttempt((n) => n + 1)}>Try again</button>
        </div>
      )}
      {load.status === 'ready' && (
        <div className="card" data-testid="suite-form">
          {notKeycloak && (
            <div role="alert" data-variant="warning" className="bh-alert" data-testid="suite-not-keycloak">
              A suite needs Keycloak as the sign-in provider. This project uses built-in sign-in. <a href={link(`/p/${projectId}/keycloak`)}>Open the Keycloak section</a> to switch it on.
            </div>
          )}
          <p className="muted" data-testid="suite-scope">
            This page covers one path only: a new project created inside a suite. Moving an existing app into a suite, or merging separate user lists, are described in the
            generated README as guidance; they are not automated.
          </p>
          <label htmlFor={ids.enabled} className="bh-checks">
            <input id={ids.enabled} type="checkbox" checked={form.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
            <span>Part of a suite</span>
          </label>
          {form.enabled && (
            <div className="bh-grid">
              <label htmlFor={ids.suiteId}>
                Suite id
                <input
                  id={ids.suiteId} value={form.suiteId} maxLength={MAX_SUITE_ID_LENGTH + 5} aria-invalid={h.suiteId !== null}
                  aria-describedby={`${ids.suiteId}-hint`} placeholder="acme" onChange={(e) => set({ suiteId: e.target.value })}
                />
                <small id={`${ids.suiteId}-hint`} className="muted" data-testid="suite-id-hint">
                  {h.suiteId ?? `Lowercase letters, digits and hyphens, up to ${MAX_SUITE_ID_LENGTH} characters.`}
                </small>
              </label>
              <div>
                <span className="muted">Derived realm</span>
                <p>
                  <code data-testid="suite-realm">{form.suiteId.trim() === '' ? 'suite-<suite id>' : suiteRealm(form.suiteId)}</code>
                </p>
                <small className="muted">Set for you. Keycloak is switched to shared mode with this realm when you save.</small>
              </div>
              <label htmlFor={ids.hub}>
                Hub issuer (optional)
                <input
                  id={ids.hub} value={form.hubIssuer} aria-invalid={h.hubIssuer !== null} aria-describedby={`${ids.hub}-hint`}
                  placeholder="https://id.acme.com/realms/suite-acme" onChange={(e) => set({ hubIssuer: e.target.value })}
                />
                <small id={`${ids.hub}-hint`} className="muted" data-testid="suite-hub-hint">
                  {h.hubIssuer ?? 'The address of the shared Keycloak realm. https only (http is allowed for localhost) and it ends with the realm path.'}
                </small>
              </label>
              <label htmlFor={ids.join}>
                Join state
                <select id={ids.join} value={form.joinState} onChange={(e) => set({ joinState: e.target.value as SuiteJoinState })}>
                  {JOIN_STATES.map((s) => (
                    <option key={s.value} value={s.value}>
                      {s.label}
                    </option>
                  ))}
                </select>
                <small className="muted">For your own tracking. It does not change what is generated.</small>
              </label>
            </div>
          )}
          {issues.length > 0 && (
            <div role="alert" data-variant="danger" className="bh-alert" data-testid="suite-issues">
              <ul>
                {issues.map((i) => (
                  <li key={`${i.path}:${i.code}`}>
                    <code>{i.path}</code> {i.message}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {error && (
            <div role="alert" data-variant="danger" className="bh-alert" data-testid="suite-error">
              {error}
            </div>
          )}
          {note && (
            <p role="status" data-testid="suite-note">
              {note}
            </p>
          )}
          <div className="bh-actions">
            <button onClick={() => void save(false)} disabled={busy || !dirty || hasHints(form)}>
              {busy ? 'Saving…' : 'Save'}
            </button>
            {saved && !confirmRemove && (
              <button className="outline" onClick={() => setConfirmRemove(true)} disabled={busy}>
                Remove from suite
              </button>
            )}
          </div>
          {confirmRemove && (
            <div role="alertdialog" aria-label="Confirm removal from the suite" data-testid="suite-confirm" className="bh-alert" data-variant="warning">
              <p>
                Remove this project from suite <strong>{saved?.suite_id}</strong>? Keycloak settings stay as they are; change the realm in the Keycloak section if needed.
              </p>
              <div className="bh-actions">
                <button onClick={() => void save(true)} disabled={busy}>
                  Yes, remove
                </button>
                <button className="outline" onClick={() => setConfirmRemove(false)} disabled={busy}>
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </>
  )
}
