import { useEffect, useState } from 'react'
import { TOKEN_HEADER, classifyStatus, previewUrl } from './previewAccess'
import { PAGE_SIZE, cellText, discoverEntities, extractRows, pageQuery, type Entity, type RowsPage } from './stageLogic'

async function getJson(previewId: string, path: string, token: string, doFetch: typeof fetch, signal: AbortSignal): Promise<unknown> {
  const res = await doFetch(previewUrl(previewId, path), { method: 'GET', headers: { [TOKEN_HEADER]: token, Accept: 'application/json' }, credentials: 'omit', redirect: 'error', cache: 'no-store', referrerPolicy: 'no-referrer', signal })
  if (!res.ok) {
    const f = classifyStatus(res.status)
    throw new Error(f === 'gone' ? 'This preview has ended.' : f === 'token' ? 'The preview token was not accepted.' : f === 'rate' ? 'Too many requests, wait a moment.' : `The preview answered ${res.status}.`)
  }
  return res.json()
}

/** Read-only browser over the preview's list endpoints (GET only, through the proxy). */
export function DataBrowser({ previewId, token, doFetch = fetch }: { previewId: string; token: string; doFetch?: typeof fetch }) {
  const [entities, setEntities] = useState<Entity[] | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [rowsError, setRowsError] = useState<string | null>(null)
  const error = listError ?? rowsError
  const [sel, setSel] = useState<Entity | null>(null)
  const [page, setPage] = useState(0)
  const [data, setData] = useState<RowsPage | null | 'loading'>('loading')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!token) return
    const ctl = new AbortController()
    setEntities(null); setListError(null)
    getJson(previewId, '/openapi.json', token, doFetch, ctl.signal).then((doc) => {
      const list = discoverEntities(doc)
      setEntities(list)
      // keep the selected entity and page across a Retry
      setSel((cur) => { const same = list.find((x) => x.listPath === cur?.listPath); if (!same) setPage(0); return same ?? list[0] ?? null })
    }, (e: unknown) => { if (!ctl.signal.aborted) setListError(e instanceof Error ? e.message : 'Could not load the API description') })
    return () => ctl.abort()
  }, [previewId, token, doFetch, attempt])

  useEffect(() => {
    if (!token || !sel) return
    const ctl = new AbortController()
    setData('loading'); setRowsError(null)
    getJson(previewId, `${sel.listPath}?${pageQuery(page)}`, token, doFetch, ctl.signal).then((b) => {
      const r = extractRows(b)
      if (!r) setRowsError('This endpoint does not return a list of records.')
      setData(r)
    }, (e: unknown) => { if (!ctl.signal.aborted) { setRowsError(e instanceof Error ? e.message : 'Could not load the records'); setData(null) } })
    return () => ctl.abort()
  }, [previewId, token, sel, page, doFetch, attempt])

  if (!token) return <p className="muted" data-testid="data-notoken">Add a preview token to browse the seeded data.</p>
  return (
    <div className="stage-data" data-testid="data-browser">
      <div className="hstack stage-bar">
        <label htmlFor="data-entity">Entity</label>
        <select id="data-entity" data-testid="data-entity" value={sel?.listPath ?? ''} disabled={!entities?.length}
          onChange={(e) => { setSel(entities?.find((x) => x.listPath === e.target.value) ?? null); setPage(0) }}>
          {(entities ?? []).map((x) => <option key={x.listPath} value={x.listPath}>{x.name}</option>)}
        </select>
        <span className="muted small-text">Read-only</span>
      </div>
      {error && <p role="alert" className="error-text" data-testid="data-error">{error} <button type="button" className="btn btn-sm" onClick={() => setAttempt((n) => n + 1)}>Retry</button></p>}
      {entities && entities.length === 0 && !error && <p className="muted" data-testid="data-none">This API has no list endpoints to browse.</p>}
      {sel && data === 'loading' && <p className="muted small-text" role="status">Loading…</p>}
      {sel && data && data !== 'loading' && (
        data.rows.length === 0 && page === 0 ? <p className="muted" data-testid="data-empty">No records yet.</p> : (
          <>
            <div className="stage-table-wrap" tabIndex={0} role="region" aria-label={`Records of ${sel.name}`}>
              <table className="stage-table" data-testid="data-table">
                <thead><tr>{data.columns.map((c) => <th key={c} scope="col">{c}</th>)}</tr></thead>
                <tbody>{data.rows.map((r, i) => <tr key={i} data-testid="data-row">{data.columns.map((c) => <td key={c}>{cellText(r[c])}</td>)}</tr>)}</tbody>
              </table>
            </div>
            <div className="hstack stage-bar">
              <button type="button" className="btn btn-sm" data-testid="data-prev" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Previous</button>
              <span className="small-text" data-testid="data-page">Page {page + 1}{data.total !== null ? ` of ${Math.max(1, Math.ceil(data.total / PAGE_SIZE))}` : ''}</span>
              <button type="button" className="btn btn-sm" data-testid="data-next" disabled={data.rows.length < PAGE_SIZE || (data.total !== null && (page + 1) * PAGE_SIZE >= data.total)} onClick={() => setPage((p) => p + 1)}>Next</button>
            </div>
          </>
        )
      )}
    </div>
  )
}
