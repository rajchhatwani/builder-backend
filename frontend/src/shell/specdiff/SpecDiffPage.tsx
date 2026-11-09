import { useCallback, useEffect, useId, useMemo, useState } from 'react'
import { api } from '../../api/client'
import { MARKS, changeText, clearBaseline, diffSpecs, loadBaseline, parseSpecText, saveBaseline } from './diffLogic'
import type { Baseline, DiffModel } from './diffLogic'

type Spec = Record<string, unknown>
type Load = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; spec: Spec }
/** Where the baseline came from: a stored snapshot (survives reloads) or JSON pasted/uploaded now (this visit only). */
type Source = { kind: 'snapshot'; savedAt: string } | { kind: 'pasted' }

const store = (): Storage | null => {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

export function SpecDiffPage({ projectId }: { projectId: string }) {
  const [load, setLoad] = useState<Load>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  const [baseline, setBaseline] = useState<{ spec: Spec; source: Source } | null>(() => {
    const s = store()
    const b: Baseline | null = s ? loadBaseline(s, projectId) : null
    return b ? { spec: b.spec, source: { kind: 'snapshot', savedAt: b.savedAt } } : null
  })
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const textId = useId()
  const fileId = useId()

  useEffect(() => {
    let cancelled = false
    setLoad({ status: 'loading' })
    api
      .getSpecJson(projectId)
      .then((spec) => {
        if (!cancelled) setLoad({ status: 'ready', spec })
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoad({ status: 'error', message: err instanceof Error ? err.message : 'Could not load the project' })
      })
    return () => {
      cancelled = true
    }
  }, [projectId, attempt])

  const current = load.status === 'ready' ? load.spec : null
  const model: DiffModel | null = useMemo(() => (current && baseline ? diffSpecs(baseline.spec, current) : null), [current, baseline])

  const snapshot = useCallback(() => {
    if (!current) return
    const s = store()
    const saved = s ? saveBaseline(s, projectId, current) : null
    if (saved) {
      setBaseline({ spec: saved.spec, source: { kind: 'snapshot', savedAt: saved.savedAt } })
      setError(null)
    } else {
      setBaseline({ spec: current, source: { kind: 'pasted' } })
      setError('This browser would not store the snapshot, so it is kept only until you leave this page.')
    }
  }, [current, projectId])

  const usePasted = (raw: string) => {
    const parsed = parseSpecText(raw)
    if (!parsed.ok) {
      setError(parsed.error)
      return
    }
    setError(null)
    setBaseline({ spec: parsed.spec, source: { kind: 'pasted' } })
  }

  const onFile = async (file: File | undefined) => {
    if (!file) return
    const raw = await file.text()
    setText(raw)
    usePasted(raw)
  }

  const clear = () => {
    const s = store()
    if (s) clearBaseline(s, projectId)
    setBaseline(null)
    setError(null)
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Visual spec diff</h1>
          <p>See what changed between a baseline and the spec as it is now. Save a snapshot before you edit, or paste an earlier spec.</p>
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
        <>
          <div className="card">
            <h2>Baseline</h2>
            <p data-testid="specdiff-source">
              {baseline === null
                ? 'No baseline yet.'
                : baseline.source.kind === 'snapshot'
                  ? `Baseline: snapshot saved ${baseline.source.savedAt}`
                  : 'Baseline: pasted spec (kept until you leave this page)'}
            </p>
            <div className="row">
              <button onClick={snapshot}>Save current spec as baseline</button>
              <button onClick={() => setAttempt((n) => n + 1)}>Reload current spec</button>
              {baseline && <button onClick={clear}>Clear baseline</button>}
            </div>
            <div className="field">
              <label htmlFor={textId}>Baseline spec (JSON)</label>
              <textarea id={textId} rows={6} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
            </div>
            <div className="field">
              <label htmlFor={fileId}>Or upload a spec file</label>
              <input id={fileId} type="file" accept=".json,application/json" onChange={(e) => void onFile(e.target.files?.[0])} />
            </div>
            <button onClick={() => usePasted(text)}>Use as baseline</button>
            {error && (
              <p role="alert" data-testid="specdiff-error">
                {error}
              </p>
            )}
          </div>

          {model === null && (
            <div className="card empty-hero" data-testid="specdiff-nobaseline">
              <h2>No baseline to compare with</h2>
              <p>Save the current spec as a baseline, then change something and come back. Or paste an earlier spec above.</p>
            </div>
          )}
          {model !== null && model.total === 0 && (
            <div className="card empty-hero" data-testid="specdiff-empty">
              <h2>No differences</h2>
              <p>The current spec matches the baseline.</p>
            </div>
          )}
          {model !== null && model.total > 0 && <Result model={model} />}
        </>
      )}
    </>
  )
}

function Result({ model }: { model: DiffModel }) {
  return (
    <div data-testid="specdiff-result">
      <p data-testid="specdiff-summary">
        {model.total} {model.total === 1 ? 'difference' : 'differences'} (+ added, - removed, ~ changed)
      </p>
      {model.truncated && <p role="status">Only the first part of a large diff is shown.</p>}
      {model.sections.map((s) => (
        <section key={s.id} className="card" aria-labelledby={`specdiff-${s.id}`}>
          <h2 id={`specdiff-${s.id}`}>
            {s.label} ({s.items.length})
          </h2>
          <ul>
            {s.items.map((item) => (
              <li key={item.key} data-testid="specdiff-item">
                <strong>
                  {MARKS[item.kind].mark} {MARKS[item.kind].word}
                </strong>{' '}
                <code>{item.key}</code>
                {item.changes.length > 0 && (
                  <ul>
                    {item.changes.map((c) => (
                      <li key={c.label}>
                        <code>{changeText(c)}</code>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}
