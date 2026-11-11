import { useCallback, useEffect, useRef, useState } from 'react'
import { aiApi } from './aiApi'
import {
  checkFiles, coverage, coveredByList, groupItems, isOpenQuestion, sourceLabel, startCheck, statusLabel,
} from './requirementsLogic'
import type { RequirementItem, RequirementQuestion, RequirementsMap } from './types'
import { errMsg, runLink } from './useRunParam'

function ItemRow({ item, busy, onSave }: { item: RequirementItem; busy: boolean; onSave: (i: RequirementItem, text: string, status: string) => void }) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(item.text)
  const out = item.status === 'out_of_scope'
  const by = coveredByList(item)
  return (
    <li className="ai-item" data-testid="req-item" data-status={item.status}>
      {editing ? (
        <>
          <textarea aria-label="Requirement text" value={text} onChange={(e) => setText(e.target.value)} rows={2} maxLength={2000} />
          <div className="hstack">
            <button className="small" disabled={busy || !text.trim()} onClick={() => { onSave(item, text.trim(), item.status); setEditing(false) }}>Save</button>
            <button className="small outline" onClick={() => { setText(item.text); setEditing(false) }}>Cancel</button>
          </div>
        </>
      ) : (
        <>
          <p className={out ? 'ai-struck' : undefined}>{item.text}</p>
          <p className="muted small-text">
            <span data-testid="req-source">From {sourceLabel(item)}</span>
            {' · '}
            <span className={`badge ${item.status === 'covered' ? '' : 'badge-muted'}`} data-testid="req-status">{statusLabel(item.status)}</span>
            {by.length > 0 && <span> by {by.join(', ')}</span>}
          </p>
          <div className="hstack">
            <button className="small outline" disabled={busy} onClick={() => setEditing(true)}>Edit</button>
            <button className="small outline" disabled={busy} onClick={() => onSave(item, item.text, out ? 'open' : 'out_of_scope')}>
              {out ? 'Put back in scope' : 'Mark out of scope'}
            </button>
            {!out && (
              <button className="small outline" data-testid="req-unmet" disabled={busy} onClick={() => onSave(item, item.text, item.status === 'unmet' ? 'open' : 'unmet')}>
                {item.status === 'unmet' ? 'Not an accepted gap' : 'Accept as gap'}
              </button>
            )}
          </div>
        </>
      )}
    </li>
  )
}

function QuestionRow({ q, busy, onAnswer }: { q: RequirementQuestion; busy: boolean; onAnswer: (q: RequirementQuestion, body: { answer?: string; accept_assumption?: boolean }) => void }) {
  const [text, setText] = useState('')
  const open = isOpenQuestion(q)
  return (
    <li className="ai-item" data-testid="req-question" data-state={q.state}>
      <p><strong>{q.text}</strong></p>
      {q.assumption && <p className="muted small-text">If you do not answer, the agent will assume: {q.assumption}</p>}
      {!open && <p className="small-text" data-testid="question-resolved">{q.answer ? `Answer: ${q.answer}` : 'Assumption accepted.'}</p>}
      {open && (
        <div className="hstack">
          <input aria-label="Your answer" value={text} onChange={(e) => setText(e.target.value)} maxLength={2000} placeholder="Your answer" />
          <button className="small" disabled={busy || !text.trim()} onClick={() => onAnswer(q, { answer: text.trim() })}>Answer</button>
          {q.assumption && <button className="small outline" disabled={busy} onClick={() => onAnswer(q, { accept_assumption: true })}>Accept assumption</button>}
        </div>
      )}
    </li>
  )
}

/** F3-1: describe what you want (prompt + documents), review the requirements map, answer questions, start the build. */
export function IntakePage({ projectId }: { projectId: string }) {
  const [map, setMap] = useState<RequirementsMap | null>(null)
  const [loading, setLoading] = useState(true)
  const [prompt, setPrompt] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [fileErrors, setFileErrors] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [confirming, setConfirming] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    try { const m = await aiApi.getRequirements(projectId); setMap(m.items.length ? m : null) } catch (e) {
      // 404 = nothing submitted yet
      if ((e as { status?: number }).status !== 404) setError(errMsg(e))
    } finally { setLoading(false) }
  }, [projectId])
  useEffect(() => { void load() }, [load])

  const run = async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true); setError('')
    try { return await fn() } catch (e) { setError(errMsg(e)); return undefined } finally { setBusy(false) }
  }

  const pick = (list: FileList | null) => {
    const all = [...(list ?? [])]
    const { ok, errors } = checkFiles(all)
    setFileErrors(errors)
    setFiles((cur) => [...cur, ...ok.map((i) => all[i])])
    if (fileRef.current) fileRef.current.value = ''
  }

  const submit = async () => {
    const m = await run(() => aiApi.intake(projectId, prompt.trim(), files))
    if (m) { setMap(m); setPrompt(''); setFiles([]) }
  }
  const saveItem = async (item: RequirementItem, text: string, status: string) => {
    const m = await run(() => aiApi.putItem(projectId, { id: item.id, text, status }))
    if (m) setMap(m)
  }
  const answer = async (q: RequirementQuestion, body: { answer?: string; accept_assumption?: boolean }) => {
    const m = await run(() => aiApi.answer(projectId, q.id, body))
    if (m) setMap(m)
  }
  const start = async (accept: boolean) => {
    const r = await run(() => aiApi.startRun(projectId, accept))
    if (r) window.location.hash = runLink(projectId, 'build', r.id).slice(1)
  }

  const check = startCheck(map)
  const cov = map ? coverage(map.items) : null
  const canSubmit = !busy && (prompt.trim().length > 0 || files.length > 0)

  return (
    <section data-testid="intake-page">
      <h1>Describe what you want built</h1>
      <p className="muted">Write it in your own words and add any documents you have. You will see exactly what we understood before anything is built.</p>

      <div className="card ai-box">
        <label htmlFor="ai-prompt">What should the backend do?</label>
        <textarea id="ai-prompt" rows={8} value={prompt} maxLength={50000} onChange={(e) => setPrompt(e.target.value)}
          placeholder="For example: a leave-request system where employees ask for time off and managers approve it." />
        <div className="hstack">
          <input ref={fileRef} type="file" multiple accept=".pdf,.txt,.md,.docx,.xlsx,application/pdf,text/plain,text/markdown,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" aria-label="Add documents" onChange={(e) => pick(e.target.files)} />
          <button disabled={!canSubmit} onClick={() => void submit()} data-testid="intake-submit">{busy ? 'Working…' : map ? 'Add to requirements' : 'Understand my request'}</button>
        </div>
        {files.length > 0 && (
          <ul className="ai-files" data-testid="intake-files">
            {files.map((f, i) => (
              <li key={`${f.name}-${i}`}>{f.name} <button className="small ghost" aria-label={`Remove ${f.name}`} onClick={() => setFiles(files.filter((_, j) => j !== i))}>Remove</button></li>
            ))}
          </ul>
        )}
        {fileErrors.map((m) => <small key={m} className="bh-error" role="alert">{m}</small>)}
      </div>

      {error && <p className="bh-error" role="alert" data-testid="intake-error">{error}</p>}
      {loading && <p className="empty-state">Loading…</p>}

      {map && cov && (
        <div data-testid="requirements-map">
          <h2>What we understood</h2>
          <p data-testid="coverage-summary">
            {cov.covered} of {cov.inScope} items covered ({cov.pct}%)
            {cov.outOfScope > 0 && `, ${cov.outOfScope} out of scope`}
          </p>
          {groupItems(map.items).map((g) => (
            <div key={g.kind} className="card" data-testid="req-group" data-kind={g.kind}>
              <h3>{g.label} <span className="badge badge-muted">{g.items.length}</span></h3>
              <ul className="ai-list">{g.items.map((it) => <ItemRow key={it.id} item={it} busy={busy} onSave={(i, t, s) => void saveItem(i, t, s)} />)}</ul>
            </div>
          ))}
          {map.questions.length > 0 && (
            <div className="card" data-testid="questions">
              <h3>Questions for you</h3>
              <ul className="ai-list">{map.questions.map((q) => <QuestionRow key={q.id} q={q} busy={busy} onAnswer={(qq, b) => void answer(qq, b)} />)}</ul>
            </div>
          )}

          <div className="hstack">
            <button disabled={busy || !check.canStart} onClick={() => (check.needsConfirm ? setConfirming(true) : void start(false))} data-testid="start-build">Start build</button>
            {!check.canStart && <small className="muted">{check.reason}</small>}
          </div>
          {confirming && (
            <div className="card" role="alertdialog" aria-label="Confirm assumptions" data-testid="confirm-assumptions">
              <p>{check.openCount} {check.openCount === 1 ? 'question is' : 'questions are'} still open. If you start now, the agent builds on its assumptions for them.</p>
              <div className="hstack">
                <button disabled={busy} onClick={() => void start(true)}>Accept assumptions and start</button>
                <button className="outline" onClick={() => setConfirming(false)}>Go back and answer</button>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
