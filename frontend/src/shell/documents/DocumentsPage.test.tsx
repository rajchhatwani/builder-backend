import axe from 'axe-core'
import { act, createElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { click, flush, mount, q, qa, setInput } from '../ai/testUtils'
import { DocumentsPage } from './DocumentsPage'

const TEXT = 'Invoice Acme\nTotal: 1250.00 EUR\nVendor: Acme Ltd'
const fld = (o: Record<string, unknown>) => ({ name: 'total', value: '1250.00', confidence_bp: 9200, anchor: { page: 1, start: 20, end: 27, quote: '1250.00' }, corrected: false, original_value: null, review_required: false, ...o })
const DOC = (o: Record<string, unknown> = {}) => ({
  id: 'd1', kind: 'invoice', title: 'Acme March', status: 'needs_review', call_id: 'c', content: TEXT, reject_reason: null,
  fields: [fld({}), fld({ name: 'vendor', value: 'Acme Ltd', confidence_bp: 6150, anchor: { page: 1, start: 900, end: 908, quote: 'Acme Ltd' }, review_required: true }), fld({ name: 'po', value: null, confidence_bp: 0, anchor: null, review_required: true })],
  ...o,
})
const D2 = DOC({ id: 'd2', title: 'Beta April', status: 'needs_review' })
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })
const err = (status: number, code: string) => json({ code, message: 'raw', details: [] }, status)

function api(over: (m: string, url: string, body: unknown) => Response | undefined = () => undefined, items: unknown[] = [DOC(), D2], total = items.length) {
  const calls: { m: string; url: string; body: Record<string, unknown> | null; auth?: string }[] = []
  const state: Record<string, unknown> = {} // what the server would now answer for a document after a successful action
  const f = vi.fn(async (url: string, init: RequestInit) => {
    const m = init.method ?? 'GET'
    const body = init.body ? JSON.parse(init.body as string) : null
    calls.push({ m, url, body, auth: (init.headers as Record<string, string>).Authorization })
    const o = over(m, url, body)
    if (o) return o
    if (m === 'GET' && /\/ai\/documents\?/.test(url)) return json({ items, total, limit: 20, offset: Number(/offset=(\d+)/.exec(url)?.[1] ?? 0) })
    if (m === 'GET') { const id = url.split('/ai/documents/')[1]; const d = (state[id] ?? (items as { id: string }[]).find((x) => x.id === id)); return d ? json(d) : err(404, 'not_found') }
    if (url.endsWith('/approve')) return json((state.d1 = DOC({ status: 'approved', content: undefined })))
    if (url.endsWith('/reject')) return json((state.d1 = DOC({ status: 'rejected', reject_reason: body?.reason ?? null })))
    if (url.endsWith('/correct')) return json((state.d1 = DOC({ fields: [fld({ value: body?.value, corrected: true, confidence_bp: 10000, original_value: '1250.00' })] })))
    return json({}, 404)
  }) as unknown as typeof fetch
  return { f, calls }
}
const el = (f: typeof fetch, props: Record<string, unknown> = {}) => createElement(DocumentsPage, { projectId: 'p', origin: 'http://gen.test', doFetch: f, ...props })
async function load(f: typeof fetch, props: Record<string, unknown> = {}) {
  const host = await mount(el(f, props))
  await setInput(q('documents-token') as HTMLInputElement, 'TOK')
  await click(q('documents-load'))
  await flush()
  return host
}
const open = async (id = 'd1') => { await click(q(`document-row-${id}`)); await flush() }
const key = async (e: Element, k: string) => { await act(async () => { e.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true })) }); await flush() }

describe('DocumentsPage', () => {
  it('asks for a token first and sends it only as bearer', async () => {
    const { f, calls } = api()
    await mount(el(f))
    expect(q('documents-notoken')).not.toBeNull(); expect(calls).toHaveLength(0)
    await setInput(q('documents-token') as HTMLInputElement, 'TOK'); await click(q('documents-load'))
    expect(calls[0].url).toBe('http://gen.test/ai/documents?status=needs_review&limit=20&offset=0'); expect(calls[0].auth).toBe('Bearer TOK')
  })
  it('shows no-origin note', async () => {
    const host = await mount(el(api().f, { origin: null }))
    expect(host.querySelector('[data-testid="documents-no-origin"]')).not.toBeNull()
  })
  it('lists the queue, announces the count and filters by status', async () => {
    const { f, calls } = api()
    await load(f)
    expect(qa('document-row-d1')).toHaveLength(1); expect(qa('document-row-d2')).toHaveLength(1)
    expect(q('documents-live')!.textContent).toBe('2 Needs review documents, showing 1 to 2.')
    await setInput(q('status-filter') as HTMLSelectElement, 'approved')
    expect(calls.at(-1)!.url).toContain('status=approved')
  })
  it('shows empty and error states', async () => {
    await load(api(undefined, []).f)
    expect(q('documents-empty')!.textContent).toMatch(/No documents/)
  })
  it('shows list errors', async () => {
    await load(api((m, url) => (url.includes('?') ? err(403, 'forbidden') : undefined)).f)
    expect(q('documents-error')!.textContent).toMatch(/review roles/)
  })
  it('pages with offset', async () => {
    const { f, calls } = api(undefined, [DOC(), D2], 45)
    await load(f)
    expect((q('documents-prev') as HTMLButtonElement).disabled).toBe(true)
    await click(q('documents-next'))
    expect(calls.at(-1)!.url).toContain('offset=20')
    expect(q('documents-range')!.textContent).toBe('21 to 40 of 45')
  })
  it('roving focus: one tab stop, arrows move it', async () => {
    await load(api().f)
    const r1 = q('document-row-d1')!, r2 = q('document-row-d2')!
    expect(r1.tabIndex).toBe(0); expect(r2.tabIndex).toBe(-1)
    await key(r1, 'ArrowDown')
    expect(r2.tabIndex).toBe(0); expect(r1.tabIndex).toBe(-1); expect(document.activeElement).toBe(r2)
    await key(r2, 'Home'); expect(q('document-row-d1')!.tabIndex).toBe(0)
  })
  it('opens detail with highlights, percent confidence and low-confidence flags', async () => {
    await load(api().f); await open()
    expect(q('document-detail')).not.toBeNull()
    expect(q('highlight-total')!.textContent).toBe('1250.00')
    expect(q('highlight-vendor')!.textContent).toBe('Acme Ltd') // out of range offsets: quote search
    expect(q('document-fallbacks')!.textContent).toMatch(/vendor.*found by text search/)
    expect(q('field-confidence-total')!.textContent).toBe('92%'); expect(q('field-low-total')).toBeNull()
    expect(q('field-confidence-vendor')!.textContent).toContain('61.5%'); expect(q('field-low-vendor')).not.toBeNull()
    expect(q('field-value-po')!.textContent).toBe('not found'); expect(q('field-low-po')).not.toBeNull()
  })
  it('respects a custom project threshold', async () => {
    await load(api().f, { reviewBelowBp: 9500 }); await open()
    expect(q('field-low-total')).not.toBeNull()
  })
  it('works when the text is missing from the answer (quotes only) and never crashes on bad anchors', async () => {
    const d = DOC({ content: undefined, fields: [fld({ anchor: { page: 1, start: 5, end: 2, quote: 'x' } })] })
    await load(api(undefined, [d]).f); await open()
    expect(q('document-no-text')).not.toBeNull(); expect(q('field-row-total')).not.toBeNull()
  })
  it('corrects a field inline and posts the value', async () => {
    const { f, calls } = api()
    await load(f); await open()
    await click(q('field-edit-total'))
    await setInput(q('field-correct-total') as HTMLInputElement, '1300.00')
    await click(q('field-save-total'))
    const c = calls.find((x) => x.url.endsWith('/fields/total/correct'))!
    expect(c.m).toBe('POST'); expect(c.body).toEqual({ value: '1300.00' })
    expect(q('document-notice')!.textContent).toBe('Field total corrected.')
    expect(q('field-confidence-total')!.textContent).toBe('100%')
  })
  it('Escape cancels an inline edit', async () => {
    await load(api().f); await open()
    await click(q('field-edit-total'))
    await key(q('field-correct-total')!, 'Escape')
    expect(q('field-correct-total')).toBeNull()
  })
  it('approves', async () => {
    const { f, calls } = api()
    await load(f); await open(); await click(q('approve-btn'))
    expect(calls.some((c) => c.url.endsWith('/d1/approve') && c.m === 'POST')).toBe(true)
    expect(q('document-notice')!.textContent).toBe('Document approved.')
    expect((q('approve-btn') as HTMLButtonElement).disabled).toBe(true)
  })
  it('rejects with a reason after confirming', async () => {
    const { f, calls } = api()
    await load(f); await open(); await click(q('reject-btn'))
    await setInput(q('reject-reason') as HTMLInputElement, 'blurry')
    await click(q('reject-btn'))
    expect(calls.find((c) => c.url.endsWith('/reject'))!.body).toEqual({ reason: 'blurry' })
    expect(q('document-status')!.textContent).toBe('Rejected')
  })
  it('shows 409, 403 and 404 messages', async () => {
    for (const [st, code, re] of [[409, 'document_closed', /already approved or rejected/], [403, 'forbidden', /review roles/], [404, 'not_found', /no longer exists/]] as const) {
      const { f } = api((m, url) => (m === 'POST' && url.endsWith('/approve') ? err(st, code) : undefined))
      const host = await load(f); await open(); await click(q('approve-btn'))
      expect(q('document-action-error')!.textContent).toMatch(re); expect(host).toBeTruthy()
      await act(async () => { document.body.innerHTML = '' })
    }
  })
  it('disables review for final documents and for non-review roles', async () => {
    await load(api(undefined, [DOC({ status: 'approved' })]).f); await open()
    expect((q('approve-btn') as HTMLButtonElement).disabled).toBe(true); expect((q('reject-btn') as HTMLButtonElement).disabled).toBe(true)
    expect((q('field-edit-total') as HTMLButtonElement).disabled).toBe(true)
  })
  it('disables review when canReview is false', async () => {
    await load(api().f, { canReview: false }); await open()
    expect((q('approve-btn') as HTMLButtonElement).disabled).toBe(true); expect(q('review-disabled-note')!.textContent).toMatch(/role/)
  })
  it('shows a detail 404', async () => {
    await load(api((m, url) => (m === 'GET' && url.endsWith('/d1') ? err(404, 'not_found') : undefined)).f); await open()
    expect(q('document-detail-error')!.textContent).toMatch(/no longer exists/)
  })
  it('review_pending lists fields and acknowledge-and-approve resends the names', async () => {
    let n = 0
    const { f, calls } = api((m, url) => (m === 'POST' && url.endsWith('/approve') && n++ === 0 ? json({ code: 'review_pending', message: 'x', details: [{ name: 'vendor' }, { name: 'total' }] }, 409) : undefined))
    await load(f); await open(); await click(q('approve-btn'))
    expect(qa('ack-list')[0].textContent).toBe('vendortotal'); expect(q('document-action-error')!.textContent).toMatch(/flagged fields/)
    expect(calls.filter((c) => c.url.endsWith('/approve'))[0].body).toBeNull()
    await click(q('ack-approve-btn'))
    expect(calls.filter((c) => c.url.endsWith('/approve'))[1].body).toEqual({ acknowledge: ['vendor', 'total'] })
    expect(q('ack-list')).toBeNull(); expect(q('document-notice')!.textContent).toBe('Document approved.')
  })
  it('shows unknown_field, self_review_forbidden and retry_with_new_key messages', async () => {
    for (const [st, code, re] of [[404, 'unknown_field', /does not exist on this document/], [403, 'self_review_forbidden', /someone else must review/], [409, 'retry_with_new_key', /new idempotency key/]] as const) {
      await load(api((m, url) => (m === 'POST' && url.endsWith('/approve') ? err(st, code) : undefined)).f); await open(); await click(q('approve-btn'))
      expect(q('document-action-error')!.textContent).toMatch(re)
      expect(q('ack-list')).toBeNull()
      await act(async () => { document.body.innerHTML = '' })
    }
  })
  it('a corrected field with no anchor shows its value without a highlight', async () => {
    const d = DOC({ fields: [fld({ value: '1300.00', anchor: null, corrected: true, confidence_bp: 10000, original_value: '1250.00' })] })
    await load(api(undefined, [d]).f); await open()
    expect(q('field-value-total')!.textContent).toBe('1300.00'); expect(q('highlight-total')).toBeNull(); expect(q('document-text')!.textContent).toBe(TEXT)
  })
  it('has no axe violations (queue, detail, reject confirm, inline edit)', async () => {
    const host = await load(api().f); await open()
    await click(q('field-edit-total')); await click(q('reject-btn'))
    const res = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' ')}`)).toEqual([])
  })
  it('has no axe violations with the acknowledge panel open', async () => {
    const host = await load(api((m, url) => (m === 'POST' && url.endsWith('/approve') ? json({ code: 'review_pending', message: 'x', details: [{ name: 'vendor' }] }, 409) : undefined)).f)
    await open(); await click(q('approve-btn'))
    const res = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' ')}`)).toEqual([])
  })
})
