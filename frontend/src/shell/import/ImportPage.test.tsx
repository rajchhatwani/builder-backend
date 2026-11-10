import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import type { ImportPreview, ImportRow } from '../../api/types'
import { ImportPage } from './ImportPage'

const m = vi.hoisted(() => ({ spec: vi.fn(), upload: vi.fn(), mapping: vi.fn(), rows: vi.fn(), fix: vi.fn(), commit: vi.fn(), cancel: vi.fn(), records: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({
  ...(await orig<typeof import('../../api/client')>()),
  api: {
    getSpecJson: m.spec, uploadImport: m.upload, setImportMapping: m.mapping, listImportRows: m.rows,
    fixImportRow: m.fix, commitImport: m.commit, cancelImport: m.cancel, listImportRecords: m.records,
  },
}))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const SPEC = { entities: [{ name: 'Invoice', fields: [{ name: 'invoice_no', required: true }, { name: 'amount', required: true }] }] }
const row = (n: number, amount: string, status: string, errors: ImportRow['errors'] = []): ImportRow => ({
  id: `r${n}`, row_no: n, raw: { No: `INV-${n}`, Total: amount }, record: null, status, errors,
})
const BAD = row(3, 'abc', 'rejected', [{ field: 'amount', code: 'invalid_decimal', message: 'must be a number' }])
const PREVIEW: ImportPreview = {
  batch_id: 'b1', entity: 'Invoice', status: 'preview', headers: ['No', 'Total'],
  mapping: {}, suggested_mapping: { invoice_no: 'No', amount: 'Total' },
  counts: { total: 3, accepted: 2, rejected: 1, duplicate: 0, fixed: 0 },
  sample: [row(1, '10', 'accepted'), row(2, '20', 'accepted'), BAD], rejected: [BAD],
}

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
async function mount() {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => { root!.render(createElement(ImportPage, { projectId: 'p' })) })
  await act(async () => { await Promise.resolve() })
}
const q = (s: string) => host.querySelector(s) as HTMLElement | null
const btn = (re: RegExp) => [...host.querySelectorAll('button')].find((b) => re.test(b.textContent ?? ''))!
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve() })
const click = async (re: RegExp) => { await act(async () => { btn(re).click() }); await flush() }
async function type(el: HTMLInputElement, value: string) {
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  await act(async () => { set.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })) })
}
async function chooseFile() {
  const input = q('input[type=file]') as HTMLInputElement
  const file = new File(['No,Total\nINV-1,10'], 'a.csv', { type: 'text/csv' })
  Object.defineProperty(input, 'files', { value: [file], configurable: true })
  await act(async () => { input.dispatchEvent(new Event('change', { bubbles: true })) })
  await click(/Upload and preview/)
}
const toReview = async () => { m.spec.mockResolvedValue(SPEC); m.upload.mockResolvedValue(PREVIEW); m.rows.mockResolvedValue({ items: [BAD], total: 1, limit: 100, offset: 0 }); await mount(); await chooseFile(); await click(/Continue/) }

afterEach(() => {
  act(() => root?.unmount()); host?.remove(); root = null
  Object.values(m).forEach((f) => f.mockReset())
})

describe('ImportPage', () => {
  it('previews the mapping prefilled from the suggestion, with counts and labelled selects', async () => {
    m.spec.mockResolvedValue(SPEC); m.upload.mockResolvedValue(PREVIEW)
    await mount()
    expect(q('label[for]')?.textContent).toBe('Entity')
    await chooseFile()
    expect(m.upload).toHaveBeenCalledWith('p', expect.any(File), 'Invoice')
    expect(q('[data-testid=import-summary]')?.textContent).toBe('3 rows, 2 ready, 1 need fixing')
    const selects = [...host.querySelectorAll('select')] as HTMLSelectElement[]
    expect(selects.map((s) => s.value)).toEqual(['No', 'Total'])
    expect(host.querySelector('label[for]')).not.toBeNull()
    selects.forEach((s) => expect(host.querySelector(`label[for="${s.id}"]`)).not.toBeNull())
    expect(host.querySelectorAll('thead th[scope=col]').length).toBeGreaterThan(4)
    expect(host.textContent).toContain('discards the fixes')
    expect(host.textContent).toContain('INV-3')
  })

  it('changing a mapping calls PUT mapping and shows the new counts', async () => {
    m.spec.mockResolvedValue(SPEC); m.upload.mockResolvedValue(PREVIEW)
    m.mapping.mockResolvedValue({ ...PREVIEW, mapping: { invoice_no: 'No' }, counts: { total: 3, accepted: 0, rejected: 3, duplicate: 0, fixed: 0 } })
    await mount(); await chooseFile()
    const sel = host.querySelectorAll('select')[1] as HTMLSelectElement
    await act(async () => { sel.value = ''; sel.dispatchEvent(new Event('change', { bubbles: true })) })
    await flush()
    expect(m.mapping).toHaveBeenCalledWith('p', 'b1', { invoice_no: 'No', amount: null })
    expect(q('[data-testid=import-summary]')?.textContent).toContain('3 need fixing')
  })

  it('fixes a rejected row, then commits and lists the records', async () => {
    await toReview()
    expect(q('[data-testid=import-row]')?.textContent).toContain('must be a number')
    const input = q('input[id]:not([type=file])') as HTMLInputElement
    expect(host.querySelector(`label[for="${input.id}"]`)?.textContent).toBe('Fix amount (row 3)')
    expect(input.value).toBe('abc')
    m.fix.mockResolvedValue({ ...BAD, status: 'fixed', errors: [] })
    await type(input, '30')
    await click(/Save row 3/)
    expect(m.fix).toHaveBeenCalledWith('p', 'b1', 'r3', { amount: '30' })
    expect(q('[data-testid=import-no-problems]')).not.toBeNull()
    expect(q('[data-testid=import-summary]')?.textContent).toBe('3 rows, 3 ready, 0 need fixing')
    m.commit.mockResolvedValue({ batch_id: 'b1', status: 'committed', created: 3, duplicate: 0, rejected: 0 })
    m.records.mockResolvedValue({ items: [{ id: 'x', entity: 'Invoice', data: { invoice_no: 'INV-1' }, batch_id: 'b1', created_at: '' }], total: 1, limit: 20, offset: 0 })
    await click(/Commit 3 rows/)
    expect(q('[data-testid=import-result]')?.textContent).toContain('3 created, 0 already imported, 0 rejected')
    expect(q('[data-testid=import-records]')?.textContent).toContain('invoice_no: INV-1')
  })

  it('keeps a row in the queue when the fix is still invalid', async () => {
    await toReview()
    m.fix.mockResolvedValue({ ...BAD, errors: [{ field: 'amount', code: 'x', message: 'still wrong' }] })
    await type(q('input[id]:not([type=file])') as HTMLInputElement, 'zzz')
    await click(/Save row 3/)
    expect(q('[data-testid=import-row]')?.textContent).toContain('still wrong')
  })

  it('shows a clear message with the limit when the commit hits the quota', async () => {
    await toReview()
    m.commit.mockRejectedValue(new ApiError(429, { code: 'quota_exceeded', message: 'quota', details: [{ metric: 'imports.rows', limit: 100, used: 100 }] }))
    await click(/Commit 2 rows/)
    const alert = q('[data-testid=import-error]')
    expect(alert?.textContent).toContain('100 imported rows')
    expect(alert?.textContent).toContain('Nothing was imported')
    expect(q('[data-testid=import-result]')).toBeNull()
  })

  it('asks before a mapping change that would discard row fixes, and keeps them on cancel', async () => {
    await toReview()
    m.fix.mockResolvedValue({ ...BAD, status: 'fixed', errors: [] })
    await type(q('input[id]:not([type=file])') as HTMLInputElement, '30')
    await click(/Save row 3/)
    await click(/Back to columns/)
    const sel = host.querySelectorAll('select')[1] as HTMLSelectElement
    await act(async () => { sel.value = ''; sel.dispatchEvent(new Event('change', { bubbles: true })) })
    await flush()
    expect(q('[data-testid=mapping-confirm]')?.textContent).toContain('discards the 1 fix')
    expect(m.mapping).not.toHaveBeenCalled()
    await click(/Keep my fixes/)
    expect(q('[data-testid=mapping-confirm]')).toBeNull()
    expect(m.mapping).not.toHaveBeenCalled()
    m.mapping.mockResolvedValue({ ...PREVIEW, mapping: { invoice_no: 'No' }, counts: { total: 3, accepted: 0, rejected: 3, duplicate: 0, fixed: 0 } })
    await act(async () => { sel.value = ''; sel.dispatchEvent(new Event('change', { bubbles: true })) })
    await click(/Change column and discard fixes/)
    expect(m.mapping).toHaveBeenCalledWith('p', 'b1', { invoice_no: 'No', amount: null })
    expect(q('[data-testid=mapping-confirm]')).toBeNull()
  })

  it('pages the review queue past 100 rows', async () => {
    const many = Array.from({ length: 100 }, (_, i) => row(i + 10, 'abc', 'rejected', [{ field: 'amount', code: 'x', message: 'bad' }]))
    const more = Array.from({ length: 20 }, (_, i) => row(i + 110, 'abc', 'rejected', [{ field: 'amount', code: 'x', message: 'bad' }]))
    m.spec.mockResolvedValue(SPEC)
    m.upload.mockResolvedValue({ ...PREVIEW, counts: { total: 120, accepted: 0, rejected: 120, duplicate: 0, fixed: 0 }, rejected: many })
    m.rows.mockResolvedValueOnce({ items: many, total: 120, limit: 100, offset: 0 }).mockResolvedValueOnce({ items: more, total: 120, limit: 100, offset: 100 })
    await mount(); await chooseFile(); await click(/Continue/)
    expect(host.querySelectorAll('[data-testid=import-row]').length).toBe(100)
    await click(/Show more rows \(100 of 120\)/)
    expect(m.rows).toHaveBeenLastCalledWith('p', 'b1', 'rejected', 100, 100)
    expect(host.querySelectorAll('[data-testid=import-row]').length).toBe(120)
    expect(q('[data-testid=import-load-more]')).toBeNull()
  })

  it('shows an empty state without entities', async () => {
    m.spec.mockResolvedValue({ entities: [] })
    await mount()
    expect(q('[data-testid=import-empty]')).not.toBeNull()
    expect(q('input[type=file]')).toBeNull()
  })

  it('shows an upload error and a retryable load error', async () => {
    m.spec.mockRejectedValueOnce(new Error('boom')); m.spec.mockResolvedValue(SPEC)
    await mount()
    expect(q('[role=alert]')?.textContent).toContain('boom')
    await click(/Try again/)
    expect(q('input[type=file]')).not.toBeNull()
    m.upload.mockRejectedValue(new Error('The file is not a CSV'))
    await chooseFile()
    expect(q('[data-testid=import-error]')?.textContent).toContain('not a CSV')
    expect(q('input[type=file]')).not.toBeNull()
  })
})
