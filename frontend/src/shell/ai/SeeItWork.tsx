import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../../api/client'
import { BASE_URL } from '../../api/session'
import { aiApi } from './aiApi'
import {
  READY_TIMEOUT_MS, STEP_LABEL, STEP_ORDER, acceptance, callPreview, createdId, crudComplete, editedBody, entitiesOf, evidence, exampleBody, isDeadPreview,
  isLivePreview, isReady, itemPath, judge, POLL_MS, previewBase, previewRefusal, previewStateText, rememberToken, tokenFor,
  type Entity, type StepId, type StepResult,
} from './seeItLogic'
import type { Preview } from './types'
import { errMsg } from './useRunParam'

interface Props { projectId: string; workspaceId?: string | null; pollMs?: number; readyTimeoutMs?: number; fetchImpl?: typeof fetch }
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** F3-7: guided check that the built backend works. The preview token lives in memory only. */
export function SeeItWork({ projectId, workspaceId = null, pollMs = POLL_MS, readyTimeoutMs = READY_TIMEOUT_MS, fetchImpl }: Props) {
  const [preview, setPreview] = useState<Preview | null>(null)
  const [error, setError] = useState('')
  const [quota, setQuota] = useState<Preview | null>(null)
  const [doc, setDoc] = useState<unknown>(null)
  const [entities, setEntities] = useState<Entity[]>([])
  const [entityName, setEntityName] = useState('')
  const [results, setResults] = useState<Partial<Record<StepId, StepResult>>>({})
  const [busy, setBusy] = useState(false)
  const created = useRef<string | null>(null)
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])

  const set = (id: StepId, r: StepResult) => { if (alive.current) setResults((p) => ({ ...p, [id]: r })) }
  const entity = entities.find((e) => e.name === entityName) ?? null
  const base = preview ? previewBase(BASE_URL, preview.url_path) : null
  const token = preview ? tokenFor(preview.id) : null
  const doFetch = fetchImpl ?? ((...a: Parameters<typeof fetch>) => fetch(...a))

  const loadEndpoints = useCallback(async (p: Preview) => {
    const tk = tokenFor(p.id)
    if (!tk) throw new Error('The preview token is only in memory while this page is open; start a new preview.')
    const b = previewBase(BASE_URL, p.url_path)
    const r = await callPreview({ base: b, token: tk, method: 'GET', path: '/openapi.json' }, doFetch)
    if (r.status !== 200 || !r.json) {
      set('endpoints', { verdict: 'fail', summary: `The API description answered ${r.status}`, ...evidence('GET', '/openapi.json', undefined, r) })
      return
    }
    const list = entitiesOf(r.json)
    setDoc(r.json); setEntities(list); setEntityName(list.find(crudComplete)?.name ?? list[0]?.name ?? '')
    set('endpoints', list.length
      ? { verdict: 'pass', summary: `${list.length} data type${list.length === 1 ? '' : 's'} with generated endpoints` }
      : { verdict: 'fail', summary: 'The backend describes no data endpoints. Add a data type first.', ...evidence('GET', '/openapi.json', undefined, r) })
  }, [doFetch]) // eslint-disable-line react-hooks/exhaustive-deps

  const waitReady = async (p0: Preview): Promise<Preview> => {
    let p = p0
    const t0 = Date.now()
    while (!isReady(p.state)) {
      if (isDeadPreview(p.state)) throw new Error(p.error ? `The preview is ${p.state}: ${p.error}` : `The preview is ${previewStateText(p.state).toLowerCase()}.`)
      if (Date.now() - t0 > readyTimeoutMs) throw new Error('The preview took too long to start. Try again in a minute.')
      await sleep(pollMs)
      if (!alive.current) throw new Error('stopped')
      p = await aiApi.getPreview(projectId, p.id)
      setPreview(p)
    }
    return p
  }

  const begin = async (rotateId?: string) => {
    setBusy(true); setError(''); setQuota(null); setResults({}); setEntities([]); created.current = null
    set('preview', { verdict: 'running', summary: 'Starting the preview…' })
    try {
      let p: Preview
      if (rotateId) {
        const r = await aiApi.rotatePreviewToken(projectId, rotateId)
        rememberToken(r.id, r.token); p = r
      } else {
        const live = (await aiApi.listPreviews(projectId)).find((x) => isLivePreview(x.state) && tokenFor(x.id) && x.workspace_id === workspaceId)
        if (live) p = live
        else { const r = await aiApi.createPreview(projectId, workspaceId); rememberToken(r.id, r.token); p = r }
      }
      setPreview(p)
      p = await waitReady(p)
      set('preview', { verdict: 'pass', summary: `${previewStateText(p.state)}. Preview data only: nothing here is real.` })
      await loadEndpoints(p)
    } catch (e) {
      if (!alive.current) return
      const msg = e instanceof ApiError ? previewRefusal(e.code, e.message) : errMsg(e)
      setError(msg)
      set('preview', { verdict: 'fail', summary: msg })
      if (e instanceof ApiError && e.code === 'preview_quota') {
        aiApi.listPreviews(projectId).then((l) => { if (alive.current) setQuota(l.find((x) => isLivePreview(x.state)) ?? null) }, () => undefined)
      }
    } finally { if (alive.current) setBusy(false) }
  }

  const tryStep = async (step: 'list' | 'create' | 'read' | 'update'): Promise<boolean> => {
    if (!base || !token || !entity) return false
    const op = step === 'list' ? entity.list : step === 'create' ? entity.create : step === 'read' ? entity.read : entity.update
    if (!op) { set(step, { verdict: 'fail', summary: `This data type has no ${step} endpoint.` }); return false }
    set(step, { verdict: 'running', summary: 'Sending…' })
    let path = op.path
    let body: ReturnType<typeof exampleBody>
    try {
      if (step === 'read' || step === 'update') {
        if (!created.current) { set(step, { verdict: 'fail', summary: 'Create a record first.' }); return false }
        path = itemPath(entity, created.current)
      }
      if (step === 'create') body = exampleBody(doc, op)
      if (step === 'update') body = editedBody(exampleBody(doc, entity.create ?? op))
      const r = await callPreview({ base, token, method: op.method, path, body }, doFetch)
      if (step === 'create') created.current = createdId(r.json)
      const v = judge(step, r, created.current)
      set(step, { verdict: v.ok ? 'pass' : 'fail', summary: v.summary, ...evidence(op.method, path, body, r) })
      return v.ok
    } catch (e) {
      set(step, { verdict: 'fail', summary: errMsg(e), ...evidence(op.method, path, body, null) })
      return false
    }
  }

  const runAll = async () => {
    setBusy(true); created.current = null
    for (const s of ['list', 'create', 'read', 'update'] as const) { if (!(await tryStep(s))) break }
    if (alive.current) setBusy(false)
  }

  const acc = acceptance(results)
  const ready = !!preview && isReady(preview.state) && results.endpoints?.verdict === 'pass' && !!token
  const canTry = (s: StepId) => s === 'list' || s === 'create' || results.create?.verdict === 'pass'

  return (
    <section data-testid="seeit-page" aria-labelledby="seeit-title">
      <h1 id="seeit-title">See it work</h1>
      <p className="muted">A short check that the backend you built really answers. It runs in a private preview with preview data only. The preview token stays in this page and is never saved.</p>
      {error && <p className="bh-error" role="alert" data-testid="seeit-error">{error}</p>}
      {quota && (
        <p data-testid="seeit-quota"><button className="outline" disabled={busy} onClick={() => void begin(quota.id)} data-testid="seeit-rotate">Get a new token for my running preview</button></p>
      )}

      <ol className="ai-timeline" data-testid="seeit-steps">
        {STEP_ORDER.map((s) => {
          const r = results[s]
          const verdict = r?.verdict ?? 'idle'
          return (
            <li key={s} data-testid={`seeit-step-${s}`} data-verdict={verdict}>
              <div className="hstack">
                <strong>{STEP_LABEL[s]}</strong>
                <span className={`badge ${verdict === 'pass' ? '' : 'badge-muted'}`} data-testid={`seeit-verdict-${s}`}>
                  {verdict === 'pass' ? 'Pass' : verdict === 'fail' ? 'Fail' : verdict === 'running' ? 'Working…' : 'Not yet'}
                </span>
                <span className="grow" />
                {s === 'preview' && <button disabled={busy} onClick={() => void begin()} data-testid="seeit-start">{preview ? 'Start again' : 'Start the preview'}</button>}
                {(s === 'list' || s === 'create' || s === 'read' || s === 'update') && (
                  <button className="outline small" disabled={busy || !ready || !canTry(s)} onClick={() => { setBusy(true); void tryStep(s).finally(() => alive.current && setBusy(false)) }} data-testid={`seeit-try-${s}`}>Try it</button>
                )}
              </div>
              {r && <p role="status" data-testid={`seeit-summary-${s}`}>{r.summary}</p>}
              {s === 'preview' && preview && <small className="muted" data-testid="seeit-preview-state">State: {previewStateText(preview.state)}</small>}
              {s === 'endpoints' && results.endpoints?.verdict === 'pass' && (
                <div data-testid="seeit-entities">
                  <label htmlFor="seeit-entity">Data type to try</label>
                  <select id="seeit-entity" value={entityName} onChange={(e) => { setEntityName(e.target.value); created.current = null; setResults((p) => ({ preview: p.preview, endpoints: p.endpoints })) }}>
                    {entities.map((e) => <option key={e.name} value={e.name}>{e.name}</option>)}
                  </select>
                  <ul className="ai-files">
                    {entities.map((e) => (
                      <li key={e.name} data-testid="seeit-entity-row"><code>{e.name}</code>{' '}
                        {([['list', e.list], ['create', e.create], ['read', e.read], ['update', e.update]] as const).map(([k, op]) => (
                          <span key={k} className={`badge ${op ? '' : 'badge-muted'}`} data-testid={`seeit-ep-${e.name}-${k}`}>{op ? `${k}: ${op.method.toUpperCase()} ${op.path}` : `no ${k}`}</span>
                        ))}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {r?.request && (
                <details data-testid={`seeit-evidence-${s}`} open={verdict === 'fail'}>
                  <summary>Request and response</summary>
                  <pre className="ai-diff" aria-label="Request">{r.request}</pre>
                  <pre className="ai-diff" aria-label="Response">{r.response}</pre>
                </details>
              )}
            </li>
          )
        })}
      </ol>

      <div className="hstack">
        <button disabled={busy || !ready} onClick={() => void runAll()} data-testid="seeit-run-all">Run all four checks</button>
        <button className="outline" onClick={() => document.querySelector<HTMLElement>('[data-testid=workbench-toggle]')?.click()} data-testid="seeit-workbench">Open the Workbench</button>
      </div>

      <div className="card" role="status" aria-live="polite" data-testid="seeit-acceptance" data-accepted={acc.accepted} data-done={acc.done}>
        <h2>Acceptance</h2>
        <p><strong>{acc.passed} of {acc.total} passed.</strong> {acc.text}</p>
        {acc.accepted && <p className="muted small-text">The records created here are preview data and disappear with the preview.</p>}
      </div>
    </section>
  )
}
