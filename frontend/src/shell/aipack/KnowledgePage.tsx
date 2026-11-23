import { useId, useRef, useState } from 'react'
import type { PreviewSession } from '../preview/previewSession'
import { State, errText, ok2xx, useCall, type Call, type Page } from '../money/moneyShared'
import { AiPageFrame, Pager, hasArray, isObj, useGet } from './aiShared'
import { aiErrorMessage, bpText, clip, pageInfo, shortId } from './aiLogic'

interface Source { id: string; title: string; allowed_roles: string[]; owner_only: boolean; owner_id: string; chunk_count: number; created_at: string }
interface Hit { source_id: string; chunk_id: string; title: string; text: string; position: number; score_bp: number }
interface Citation { source_id: string; chunk_id: string; title: string; quote: string; score_bp: number }
interface Answer { answer: string; grounded: boolean; citations: Citation[]; call_id: string | null }
const LIMIT = 50
const WHAT = 'knowledge library'
const csv = (t: string) => t.split(',').map((x) => x.trim()).filter(Boolean)

/** Search or ask: one request at a time; an answer that arrives after a newer request (or an unmount) is dropped. */
function useQuery<T>(call: Call, path: string, body: (text: string) => unknown, check: (j: unknown) => boolean) {
  const [state, setState] = useState<{ s: 'idle' } | { s: 'loading' } | { s: 'error'; m: string } | { s: 'ok'; v: T }>({ s: 'idle' })
  const seq = useRef(0)
  const busy = useRef(false)
  async function run(text: string) {
    if (busy.current) return
    busy.current = true
    const mine = ++seq.current
    setState({ s: 'loading' })
    try {
      const r = await call('POST', path, body(text))
      if (mine !== seq.current) return
      setState(ok2xx(r.status) ? (check(r.json) ? { s: 'ok', v: r.json as T } : { s: 'error', m: 'The API answered with something unexpected.' }) : { s: 'error', m: aiErrorMessage(r.status, r.json, WHAT) })
    } catch (e) { if (mine === seq.current) setState({ s: 'error', m: errText(e, `Could not reach the ${WHAT}`) }) } finally { busy.current = false }
  }
  return { state, run }
}

function Body({ session }: { session: PreviewSession }) {
  const call = useCall(session)
  const [refresh, setRefresh] = useState(0)
  const [offset, setOffset] = useState(0)
  const sources = useGet<Page<Source>>(call, `/ai/knowledge/sources?limit=${LIMIT}&offset=${offset}`, hasArray('items'), WHAT, refresh)
  const ids = { title: useId(), text: useId(), roles: useId(), owner: useId(), q: useId(), n: useId(), ask: useId() }

  const [title, setTitle] = useState(''), [text, setText] = useState(''), [roles, setRoles] = useState(''), [ownerOnly, setOwnerOnly] = useState(false)
  const [creating, setCreating] = useState(false)
  const createBusy = useRef(false)
  const [createErr, setCreateErr] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [confirmDel, setConfirmDel] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const delBusy = useRef(false)
  const [delErr, setDelErr] = useState<string | null>(null)

  async function create() {
    setCreateErr(null); setNotice(null)
    if (!title.trim()) { setCreateErr('Enter a title.'); return }
    if (!text.trim()) { setCreateErr('Paste the text of the source.'); return }
    if (!csv(roles).length && !ownerOnly) { setCreateErr('Choose who may see this source: list at least one role, or tick "Only I can see this source".'); return }
    if (createBusy.current) return
    createBusy.current = true; setCreating(true)
    try {
      const body: Record<string, unknown> = { title: title.trim(), text }
      const r = csv(roles)
      if (r.length) body.allowed_roles = r
      if (ownerOnly) body.owner_only = true
      const res = await call('POST', '/ai/knowledge/sources', body)
      if (ok2xx(res.status)) { setNotice('Source added.'); setTitle(''); setText(''); setRoles(''); setOwnerOnly(false); setOffset(0); setRefresh((n) => n + 1) }
      else setCreateErr(aiErrorMessage(res.status, res.json, WHAT))
    } catch (e) { setCreateErr(errText(e, `Could not reach the ${WHAT}`)) } finally { createBusy.current = false; setCreating(false) }
  }
  async function remove(id: string) {
    if (delBusy.current) return
    delBusy.current = true; setDeleting(true); setDelErr(null); setNotice(null)
    try {
      const res = await call('DELETE', `/ai/knowledge/sources/${encodeURIComponent(id)}`)
      if (ok2xx(res.status)) { setNotice('Source deleted.'); setConfirmDel(null); setRefresh((n) => n + 1) }
      else { setDelErr(aiErrorMessage(res.status, res.json, WHAT)); setConfirmDel(null) }
    } catch (e) { setDelErr(errText(e, `Could not reach the ${WHAT}`)); setConfirmDel(null) } finally { delBusy.current = false; setDeleting(false) }
  }

  const [query, setQuery] = useState(''), [question, setQuestion] = useState('')
  const search = useQuery<{ hits: Hit[] }>(call, '/ai/knowledge/search', (t) => ({ query: t, limit: 5 }), hasArray('hits'))
  const ask = useQuery<Answer>(call, '/ai/knowledge/ask', (t) => ({ question: t, limit: 4 }), (j) => isObj(j) && typeof j.answer === 'string' && Array.isArray(j.citations))

  return (
    <>
      <p className="muted" data-testid="knowledge-untrusted">Source text, search hits and answers are untrusted content. They are shown as plain text only.</p>

      <div className="stack">
        <h2>Sources</h2>
        <div><button type="button" className="outline" onClick={() => setRefresh((n) => n + 1)} data-testid="sources-refresh">Refresh</button></div>
        {notice && <p role="status" data-testid="source-notice">{notice}</p>}
        {delErr && <p role="alert" className="error-text" data-testid="source-delete-error">{delErr}</p>}
        <State l={sources} id="sources" empty={(v) => v.items.length === 0} emptyText="No sources yet. Add one below.">
          {(v) => (
            <>
              <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Knowledge sources">
                <table className="stage-table" data-testid="sources-table">
                  <caption className="sr-only">Knowledge sources</caption>
                  <thead><tr><th scope="col">Title</th><th scope="col">Chunks</th><th scope="col">Visible to</th><th scope="col">Owner</th><th scope="col">Added</th><th scope="col">Actions</th></tr></thead>
                  <tbody>{v.items.map((s) => (
                    <tr key={s.id} data-testid="source-row">
                      <th scope="row">{s.title}</th><td className="num">{s.chunk_count}</td>
                      <td>{s.owner_only ? 'Owner only' : s.allowed_roles.join(', ')}</td><td>{shortId(s.owner_id)}</td><td>{s.created_at}</td>
                      <td>{confirmDel === s.id ? (
                        <span role="alertdialog" aria-label={`Confirm delete ${s.title}`} className="hstack" data-testid="source-confirm">
                          <span>Delete this source and its chunks? This cannot be undone.</span>
                          <button type="button" disabled={deleting} onClick={() => void remove(s.id)} data-testid="source-delete-yes">{deleting ? 'Deleting…' : 'Yes, delete'}</button>
                          <button type="button" className="outline" disabled={deleting} onClick={() => setConfirmDel(null)}>Cancel</button>
                        </span>
                      ) : <button type="button" className="outline small" aria-label={`Delete ${s.title}`} onClick={() => { setConfirmDel(s.id); setDelErr(null) }} data-testid="source-delete">Delete</button>}</td>
                    </tr>))}</tbody>
                </table>
              </div>
              <Pager id="sources" info={pageInfo(Number(v.total), LIMIT, offset)} onPrev={() => setOffset(Math.max(0, offset - LIMIT))} onNext={() => setOffset(offset + LIMIT)} />
            </>
          )}
        </State>
      </div>

      <form className="stack" data-testid="source-form" onSubmit={(e) => { e.preventDefault(); void create() }}>
        <h2>Add a source</h2>
        <label htmlFor={ids.title}>Title</label>
        <input id={ids.title} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} data-testid="source-title" />
        <label htmlFor={ids.text}>Text</label>
        <textarea id={ids.text} rows={6} value={text} onChange={(e) => setText(e.target.value)} data-testid="source-text" />
        <label htmlFor={ids.roles}>Allowed roles (comma separated; required unless only you can see it)</label>
        <input id={ids.roles} value={roles} onChange={(e) => setRoles(e.target.value)} data-testid="source-roles" />
        <label htmlFor={ids.owner}><input id={ids.owner} type="checkbox" checked={ownerOnly} onChange={(e) => setOwnerOnly(e.target.checked)} data-testid="source-owner" /> Only I can see this source</label>
        <div><button type="submit" disabled={creating} data-testid="source-create">{creating ? 'Adding…' : 'Add source'}</button></div>
        {createErr && <p role="alert" className="error-text" data-testid="source-create-error">{createErr}</p>}
      </form>

      <form className="stack" data-testid="search-form" onSubmit={(e) => { e.preventDefault(); if (query.trim()) void search.run(query.trim()) }}>
        <h2>Search</h2>
        <label htmlFor={ids.q}>Query</label>
        <input id={ids.q} value={query} maxLength={500} onChange={(e) => setQuery(e.target.value)} data-testid="search-query" />
        <div><button type="submit" disabled={search.state.s === 'loading' || !query.trim()} data-testid="search-run">Search</button></div>
        <State l={search.state} id="search" empty={(v) => v.hits.length === 0} emptyText="No matching passages.">
          {(v) => (
            <ol data-testid="search-hits">{v.hits.map((h) => (
              <li key={h.chunk_id} data-testid="search-hit">
                <strong>{h.title}</strong> <span className="muted">passage {h.position}, score {bpText(h.score_bp)}</span>
                <p style={{ whiteSpace: 'pre-wrap' }}>{clip(h.text)}</p>
              </li>))}
            </ol>
          )}
        </State>
      </form>

      <form className="stack" data-testid="ask-form" onSubmit={(e) => { e.preventDefault(); if (question.trim()) void ask.run(question.trim()) }}>
        <h2>Ask</h2>
        <label htmlFor={ids.ask}>Question</label>
        <input id={ids.ask} value={question} maxLength={1000} onChange={(e) => setQuestion(e.target.value)} data-testid="ask-question" />
        <div><button type="submit" disabled={ask.state.s === 'loading' || !question.trim()} data-testid="ask-run">Ask</button></div>
        <State l={ask.state} id="ask" empty={() => false} emptyText="">
          {(v) => (
            <div data-testid="ask-result">
              <p className="muted">{v.grounded ? 'Grounded in the sources below.' : 'Not grounded: no source supports this answer. Treat it with care.'}</p>
              <p style={{ whiteSpace: 'pre-wrap' }} data-testid="ask-answer">{v.answer}</p>
              {v.citations.length === 0 ? <p className="muted" data-testid="ask-no-citations">No citations.</p> : (
                <ol data-testid="ask-citations">{v.citations.map((c) => (
                  <li key={c.chunk_id} data-testid="ask-citation"><strong>{c.title}</strong> <span className="muted">score {bpText(c.score_bp)}</span><p style={{ whiteSpace: 'pre-wrap' }}>{clip(c.quote)}</p></li>))}
                </ol>
              )}
            </div>
          )}
        </State>
      </form>
    </>
  )
}

export function KnowledgePage({ projectId, session }: { projectId: string; session?: PreviewSession }) {
  return (
    <AiPageFrame projectId={projectId} session={session} testid="knowledge-page" title="Knowledge library"
      intro="Sources the AI may answer from. Search shows the matching passages; ask returns an answer with its citations.">
      {(s) => <Body session={s} />}
    </AiPageFrame>
  )
}
