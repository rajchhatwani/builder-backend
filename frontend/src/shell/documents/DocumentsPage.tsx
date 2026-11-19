import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { PreviewSessionGate } from '../preview/PreviewSessionGate'
import { usePreviewSession } from '../preview/usePreviewSession'
import type { PreviewSession } from '../preview/previewSession'
import {
  DEFAULT_REVIEW_BELOW_BP, STATUSES, STATUS_LABEL, confidencePercent, documentErrorMessage, highlightSegments, isLowConfidence, isReviewable, moveRow, pageInfo,
  parseDocJson, pendingFields, type Doc, type DocField,
} from './documentLogic'

type Page<T> = { items: T[]; total?: number; limit?: number; offset?: number }
type Load<T> = { s: 'idle' } | { s: 'loading' } | { s: 'error'; m: string } | { s: 'ok'; v: T }
const msg = (e: unknown, f: string) => (e instanceof Error ? e.message : f)
const LIMIT = 20

/** Document review queue for a generated project's AI documents pack (D34). Queue by status, anchored highlights, correct / approve / reject.
 *  Uses the dashboard-supplied preview session (tokens kept in memory only, never shown). The server decides who may review; a 403/409/404 is shown, never hidden. */
function DocumentsPageBody({ session, reviewBelowBp = DEFAULT_REVIEW_BELOW_BP, canReview = true }: { projectId: string; session: PreviewSession; reviewBelowBp?: number; canReview?: boolean }) {
  const { request } = session
  const [status, setStatus] = useState('needs_review')
  const [offset, setOffset] = useState(0)
  const [list, setList] = useState<Load<Page<Doc>>>({ s: 'idle' })
  const [refresh, setRefresh] = useState(0)
  const [selId, setSelId] = useState<string | null>(null)
  const [detail, setDetail] = useState<Load<Doc>>({ s: 'idle' })
  const [rowFocus, setRowFocus] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [reason, setReason] = useState('')
  const [pending, setPending] = useState<string[]>([])
  const [confirmReject, setConfirmReject] = useState(false)
  const statusId = useId(), reasonId = useId()
  const rowRefs = useRef(new Map<number, HTMLButtonElement>())

  const call = useCallback(async (method: string, path: string, body?: unknown) => {
    const r = await request(method, path, body)
    let json: unknown = null
    try { json = r.text ? parseDocJson(r.text) : null } catch { json = null }
    return { status: r.status, json }
  }, [request])


  useEffect(() => {
    let dead = false
    setList({ s: 'loading' })
    void (async () => {
      try {
        const r = await call('GET', `/ai/documents?status=${encodeURIComponent(status)}&limit=${LIMIT}&offset=${offset}`)
        if (dead) return
        if (r.status >= 200 && r.status < 300 && r.json && typeof r.json === 'object' && Array.isArray((r.json as Page<Doc>).items)) setList({ s: 'ok', v: r.json as Page<Doc> })
        else setList({ s: 'error', m: documentErrorMessage(r.status, r.json) })
      } catch (e) { if (!dead) setList({ s: 'error', m: msg(e, 'Could not reach the document API') }) }
    })()
    return () => { dead = true }
  }, [status, offset, refresh, call])

  useEffect(() => {
    if (!selId) { setDetail({ s: 'idle' }); return }
    let dead = false
    setDetail({ s: 'loading' })
    void (async () => {
      try {
        const r = await call('GET', `/ai/documents/${encodeURIComponent(selId)}`)
        if (dead) return
        if (r.status >= 200 && r.status < 300 && r.json && typeof r.json === 'object') setDetail({ s: 'ok', v: r.json as Doc })
        else setDetail({ s: 'error', m: documentErrorMessage(r.status, r.json) })
      } catch (e) { if (!dead) setDetail({ s: 'error', m: msg(e, 'Could not reach the document API') }) }
    })()
    return () => { dead = true }
  }, [selId, call, refresh])

  const items = list.s === 'ok' ? list.v.items : []
  const total = list.s === 'ok' ? list.v.total ?? items.length : 0
  const pg = pageInfo(total, LIMIT, offset)
  // The last page emptied (its only item was approved or rejected): step back instead of stranding the user without a pager.
  const strandedOffset = list.s === 'ok' && items.length === 0 && offset > 0 ? Math.max(0, (Math.ceil(total / LIMIT) - 1) * LIMIT) : null
  useEffect(() => {
    if (strandedOffset !== null && strandedOffset < offset) { setOffset(strandedOffset); setSelId(null); setRowFocus(0) }
  }, [strandedOffset, offset])
  const doc = detail.s === 'ok' ? detail.v : null
  const reviewable = !!doc && isReviewable(String(doc.status)) && canReview

  function choose(id: string) { setSelId(id); setError(null); setNotice(null); setEditing(null); setConfirmReject(false); setReason(''); setPending([]) }
  function onRowKey(e: React.KeyboardEvent, i: number) {
    if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(e.key)) return
    e.preventDefault()
    const n = moveRow(items.length, i, e.key)
    setRowFocus(n); rowRefs.current.get(n)?.focus()
  }

  async function act(run: () => Promise<{ status: number; json: unknown }>, ok: string) {
    setBusy(true); setError(null); setNotice(null)
    try {
      const r = await run()
      if (r.status >= 200 && r.status < 300) {
        if (r.json && typeof r.json === 'object') setDetail((cur) => { const n = r.json as Doc; return { s: 'ok', v: n.content == null && cur.s === 'ok' ? { ...n, content: cur.v.content } : n } })
        setNotice(ok); setPending([]); setEditing(null); setConfirmReject(false); setRefresh((n) => n + 1)
      } else { setPending(r.status === 409 ? pendingFields(r.json) : []); setError(documentErrorMessage(r.status, r.json)); if (r.status === 409 || r.status === 404) setRefresh((n) => n + 1) }
    } catch (e) { setError(msg(e, 'Could not reach the document API')) } finally { setBusy(false) }
  }
  const base = (d: Doc) => `/ai/documents/${encodeURIComponent(d.id)}`
  const correct = (d: Doc, name: string) => act(() => call('POST', `${base(d)}/fields/${encodeURIComponent(name)}/correct`, { value: draft.trim() === '' ? null : draft }), `Field ${name} corrected.`)
  const approve = (d: Doc, acknowledge?: string[]) => act(() => call('POST', `${base(d)}/approve`, acknowledge ? { acknowledge } : undefined), 'Document approved.')
  const reject = (d: Doc) => act(() => call('POST', `${base(d)}/reject`, reason.trim() ? { reason: reason.trim() } : {}), 'Document rejected.')

  const hl = useMemo(() => (doc && typeof doc.content === 'string' ? highlightSegments(doc.content, doc.fields ?? []) : null), [doc])

  return (
    <>

      {(
        <div className="hstack" role="group" aria-label="Queue controls">
          <label htmlFor={statusId}>Status</label>
          <select id={statusId} value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); setSelId(null); setRowFocus(0) }} data-testid="status-filter">
            {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
          </select>
          <button type="button" className="ghost small" onClick={() => setRefresh((n) => n + 1)} data-testid="documents-refresh">Refresh</button>
        </div>
      )}
      <p role="status" aria-live="polite" className="small-text muted" data-testid="documents-live">
        {list.s === 'ok' ? `${total} ${STATUS_LABEL[status] ?? status} document${total === 1 ? '' : 's'}${total > 0 ? `, showing ${pg.from} to ${pg.to}` : ''}.` : ''}
      </p>

      {list.s === 'loading' && <p className="muted" data-testid="documents-loading">Loading documents…</p>}
      {list.s === 'error' && <p role="alert" className="error-text" data-testid="documents-error">{list.m}</p>}
      {list.s === 'ok' && items.length === 0 && <p className="muted" data-testid="documents-empty">No documents with status {STATUS_LABEL[status] ?? status}.</p>}

      {list.s === 'ok' && items.length > 0 && (
        <div className="stack">
          <ul role="list" aria-label="Document queue" data-testid="document-queue" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {items.map((d, i) => (
              <li key={d.id}>
                <button
                  type="button" ref={(el) => { if (el) rowRefs.current.set(i, el); else rowRefs.current.delete(i) }}
                  tabIndex={i === Math.min(rowFocus, items.length - 1) ? 0 : -1} aria-pressed={selId === d.id}
                  aria-label={`${d.title}, ${d.kind}, ${STATUS_LABEL[String(d.status)] ?? d.status}`}
                  onClick={() => choose(d.id)} onFocus={() => setRowFocus(i)} onKeyDown={(e) => onRowKey(e, i)}
                  className={selId === d.id ? 'small' : 'outline small'} data-testid={`document-row-${d.id}`} style={{ width: '100%', textAlign: 'left' }}
                >
                  <strong>{d.title}</strong> <span className="muted">{d.kind} · {STATUS_LABEL[String(d.status)] ?? d.status}</span>
                </button>
              </li>
            ))}
          </ul>
          <div className="hstack" role="group" aria-label="Queue pages">
            <button type="button" className="outline small" disabled={!pg.hasPrev} onClick={() => { setOffset(Math.max(0, offset - LIMIT)); setSelId(null); setRowFocus(0) }} data-testid="documents-prev">Previous</button>
            <span className="small-text muted" data-testid="documents-range">{pg.from} to {pg.to} of {total}</span>
            <button type="button" className="outline small" disabled={!pg.hasNext} onClick={() => { setOffset(offset + LIMIT); setSelId(null); setRowFocus(0) }} data-testid="documents-next">Next</button>
          </div>
        </div>
      )}

      {selId && (
        <section aria-label="Document detail" className="stack" data-testid="document-detail">
          {detail.s === 'loading' && <p className="muted" data-testid="document-detail-loading">Loading document…</p>}
          {detail.s === 'error' && <p role="alert" className="error-text" data-testid="document-detail-error">{detail.m}</p>}
          {doc && (
            <>
              <h2>{doc.title} <span className="muted small-text" data-testid="document-status">{STATUS_LABEL[String(doc.status)] ?? doc.status}</span></h2>
              {doc.reject_reason && <p className="small-text muted" data-testid="document-reject-reason">Rejected: {doc.reject_reason}</p>}
              {hl ? (
                <pre data-testid="document-text" tabIndex={0} aria-label="Document text" style={{ whiteSpace: 'pre-wrap', maxHeight: 280, overflow: 'auto' }}>
                  {hl.segments.map((s, i) => s.field
                    ? <mark key={i} data-testid={`highlight-${s.field}`} title={s.field} style={{ background: '#fff8c5', color: '#4d3800', outline: '1px solid #9a6700' }}>{s.text}</mark>
                    : <span key={i}>{s.text}</span>)}
                </pre>
              ) : (
                <p className="small-text muted" data-testid="document-no-text">The source text is not part of the API answer, so only the quoted evidence per field is shown below.</p>
              )}
              {hl && hl.fallbacks.length > 0 && (
                <ul className="small-text" data-testid="document-fallbacks" aria-label="Evidence that could not be placed exactly">
                  {hl.fallbacks.map((f) => <li key={f.field}>{f.field}: {f.quote ? <q>{f.quote}</q> : 'no quote'} {f.found ? '(found by text search)' : '(not found in the text)'}</li>)}
                </ul>
              )}
              <table data-testid="document-fields">
                <caption className="sr-only">Extracted fields</caption>
                <thead><tr><th scope="col">Field</th><th scope="col">Value</th><th scope="col">Confidence</th><th scope="col">Evidence</th><th scope="col">Action</th></tr></thead>
                <tbody>
                  {doc.fields.map((f) => <FieldRow key={f.name} f={f} doc={doc} threshold={reviewBelowBp} hasText={!!hl} reviewable={reviewable} busy={busy}
                    editing={editing === f.name} draft={draft} onEdit={() => { setEditing(f.name); setDraft(f.value ?? '') }} onDraft={setDraft} onCancel={() => setEditing(null)} onSave={() => void correct(doc, f.name)} />)}
                </tbody>
              </table>
              {!reviewable && <p className="small-text muted" data-testid="review-disabled-note">{!isReviewable(String(doc.status)) ? 'This document is final and can no longer change.' : 'Your role may not review documents.'}</p>}
              <div className="hstack" role="group" aria-label="Review actions">
                <button type="button" disabled={busy || !reviewable} onClick={() => void approve(doc)} data-testid="approve-btn">Approve</button>
                {!confirmReject
                  ? <button type="button" className="outline" disabled={busy || !reviewable} onClick={() => setConfirmReject(true)} data-testid="reject-btn">Reject</button>
                  : (
                    <>
                      <label htmlFor={reasonId}>Reason (optional)</label>
                      <input id={reasonId} value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} data-testid="reject-reason" />
                      <button type="button" className="danger" disabled={busy || !reviewable} onClick={() => void reject(doc)} data-testid="reject-btn">Confirm reject</button>
                      <button type="button" className="ghost" onClick={() => setConfirmReject(false)} data-testid="reject-cancel">Keep</button>
                    </>
                  )}
              </div>
            </>
          )}
          {pending.length > 0 && doc && (
            <div className="stack" data-testid="ack-panel">
              <p className="small-text">Flagged fields still waiting for review:</p>
              <ul data-testid="ack-list" aria-label="Fields pending review">{pending.map((n) => <li key={n}>{n}</li>)}</ul>
              <button type="button" className="outline" disabled={busy || !reviewable} onClick={() => void approve(doc, pending)} data-testid="ack-approve-btn">Acknowledge and approve</button>
            </div>
          )}
          {error && <p role="alert" className="error-text" data-testid="document-action-error">{error}</p>}
          {notice && <p role="status" data-testid="document-notice">{notice}</p>}
        </section>
      )}
    </>
  )
}

export function DocumentsPage({ projectId, session, reviewBelowBp, canReview }: { projectId: string; session?: PreviewSession; reviewBelowBp?: number; canReview?: boolean }) {
  const own = usePreviewSession(projectId, { disabled: !!session })
  const s = session ?? own
  return (
    <section aria-labelledby="doc-h" data-testid="documents-page" className="stack">
      <h1 id="doc-h">Documents</h1>
      <p className="muted">Review queue for AI-extracted documents. Check each field against the source text, correct what is wrong, then approve or reject.</p>
      <PreviewSessionGate session={s} prefix="documents">
        <DocumentsPageBody key={projectId} projectId={projectId} session={s} reviewBelowBp={reviewBelowBp} canReview={canReview}/>
      </PreviewSessionGate>
    </section>
  )
}

function FieldRow({ f, threshold, hasText, reviewable, busy, editing, draft, onEdit, onDraft, onCancel, onSave }: {
  f: DocField; doc: Doc; threshold: number; hasText: boolean; reviewable: boolean; busy: boolean; editing: boolean; draft: string
  onEdit: () => void; onDraft: (v: string) => void; onCancel: () => void; onSave: () => void
}) {
  const low = isLowConfidence(f, threshold)
  const id = useId()
  return (
    <tr data-testid={`field-row-${f.name}`}>
      <th scope="row">{f.name}{f.corrected && <span className="small-text muted"> (corrected{f.original_value !== null ? `, was ${f.original_value}` : ''})</span>}</th>
      <td data-testid={`field-value-${f.name}`}>
        {editing ? (
          <>
            <label htmlFor={id} className="sr-only">New value for {f.name}</label>
            <input id={id} value={draft} onChange={(e) => onDraft(e.target.value)} onKeyDown={(e) => { if (e.key === 'Escape') onCancel(); if (e.key === 'Enter') { e.preventDefault(); onSave() } }} data-testid={`field-correct-${f.name}`} autoFocus />
          </>
        ) : (f.value ?? <span className="muted">not found</span>)}
      </td>
      <td data-testid={`field-confidence-${f.name}`}>
        {confidencePercent(f.confidence_bp)}{low && <strong data-testid={`field-low-${f.name}`} style={{ color: '#9a3412' }}> Low confidence, check this</strong>}
      </td>
      <td className="small-text">{f.anchor ? <>{hasText ? `page ${f.anchor.page}` : <q>{f.anchor.quote}</q>}</> : <span className="muted">no evidence</span>}</td>
      <td>
        {editing ? (
          <span className="hstack">
            <button type="button" className="small" disabled={busy} onClick={onSave} data-testid={`field-save-${f.name}`}>Save</button>
            <button type="button" className="ghost small" onClick={onCancel} data-testid={`field-cancel-${f.name}`}>Cancel</button>
          </span>
        ) : <button type="button" className="outline small" disabled={busy || !reviewable} aria-label={`Correct ${f.name}`} onClick={onEdit} data-testid={`field-edit-${f.name}`}>Correct</button>}
      </td>
    </tr>
  )
}
