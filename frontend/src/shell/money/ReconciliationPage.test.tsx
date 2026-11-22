import axe from 'axe-core'
import { createElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { readySession, stubSession } from '../preview/testSession'
import { click, mount, q, qa, setInput, typeInto } from '../ai/testUtils'
import { ReconciliationPage } from './ReconciliationPage'

const ACCTS = { items: [{ id: 'a1', code: '1000', name: 'Bank', currency: 'USD', exponent: 2 }], total: 1 }
const SUM = { currency: 'USD', line_count: 2, matched_count: 1, unmatched_line_count: 1, unmatched_entry_count: 1, statement_total_minor: 9007199254740993, matched_diff_minor: 0, unmatched_lines_minor: 500, unmatched_entries_minor: 300, difference_minor: 200 }
const RUN = (o: Record<string, unknown> = {}) => ({ id: 'r1', account_id: 'a1', currency: 'USD', name: 'Jan', period_start: null, period_end: null, status: 'open', line_count: 2, matched_count: 1, summary: SUM, ...o })
const line = (id: string, ext: string, amt: number) => ({ id, line_no: 1, external_id: ext, date: '2026-01-02', amount_minor: amt, currency: 'USD', reference: null })
const ent = (id: string, amt: number) => ({ id, transaction_id: 't', date: '2026-01-02', amount_minor: amt, reference: null, description: 'Sale' })
const RESULTS = (status = 'open') => ({ run: RUN({ status }), matched: [{ match: { id: 'm1', line_id: 'l1', entry_id: 'e1', method: 'auto', diff_minor: 0 }, line: line('l1', 'b1', 1000), entry: ent('e1', 1000) }], matched_total: 1, unmatched_lines: [line('l2', 'b2', 500)], unmatched_entries: [ent('e2', 300)], entries_truncated: false, summary: SUM })
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b).replace(/9007199254740992/g, '9007199254740993'), { status })

function api(over: (m: string, url: string) => Response | undefined = () => undefined, status = 'open') {
  const calls: { m: string; url: string; body?: string }[] = []
  const f = vi.fn(async (url: string, init: RequestInit) => {
    const m = init.method ?? 'GET'
    calls.push({ m, url, body: init.body as string | undefined })
    const o = over(m, url)
    if (o) return o
    if (url.includes('/ledger/accounts')) return json(ACCTS)
    if (url.includes('/results')) return json(RESULTS(status))
    if (m === 'GET' && url.includes('/reconciliation/runs')) return json({ items: [RUN()], total: 1 })
    if (m === 'POST' && url.endsWith('/reconciliation/runs')) return json(RUN(), 201)
    if (m === 'POST' || m === 'DELETE') return json(RUN(), 200)
    return json({}, 404)
  }) as unknown as typeof fetch
  return { f, calls }
}
const load = (f: typeof fetch) => mount(createElement(ReconciliationPage, { projectId: 'p', session: readySession(f) }))
const open = async () => { await click(q('recon-open')) }

describe('ReconciliationPage', () => {
  it('gates without a session', async () => {
    const { f } = api()
    const host = await mount(createElement(ReconciliationPage, { projectId: 'p', session: stubSession('no-origin') }))
    expect(q('recon-no-origin')).not.toBeNull()
    expect(host.querySelectorAll('h1')).toHaveLength(1)
    expect(f).not.toHaveBeenCalled()
  })
  it('lists runs and shows empty and error states', async () => {
    const a = api()
    await load(a.f)
    expect(qa('recon-run-row')).toHaveLength(1)
  })
  it('shows empty state', async () => {
    const { f } = api((m, u) => (m === 'GET' && u.includes('/reconciliation/runs') ? json({ items: [], total: 0 }) : undefined))
    await load(f)
    expect(q('recon-runs-empty')).not.toBeNull()
  })
  it('explains a missing reconciliation API', async () => {
    const { f } = api((_m, u) => (u.includes('/reconciliation/runs') ? json({ detail: 'Not Found' }, 404) : undefined))
    await load(f)
    expect(q('recon-runs-error')?.textContent).toMatch(/no reconciliation API/)
  })
  it('shows results with exact amounts', async () => {
    const { f } = api()
    await load(f)
    await open()
    expect(q('recon-summary')?.textContent).toContain('90,071,992,547,409.93')
    expect(q('recon-difference')?.textContent).toContain('2.00')
    expect(qa('recon-pair')).toHaveLength(1)
    expect(qa('recon-ul-row')).toHaveLength(1)
    expect(qa('recon-ue-row')).toHaveLength(1)
  })
  it('creates a run from CSV with minor-unit lines and a key', async () => {
    const { f, calls } = api()
    await load(f)
    await setInput(q('recon-account') as HTMLSelectElement, 'a1')
    await typeInto(q('recon-csv') as HTMLTextAreaElement, 'b1,2026-01-02,10.00,USD,INV-1')
    await click(q('recon-create'))
    const b = JSON.parse(calls.find((c) => c.m === 'POST' && c.url.endsWith('/reconciliation/runs'))!.body!)
    expect(b.account_id).toBe('a1')
    expect(b.lines).toEqual([{ external_id: 'b1', date: '2026-01-02', amount_minor: 1000, currency: 'USD', reference: 'INV-1' }])
    expect(b.idempotency_key.length).toBeGreaterThan(0)
    expect(q('recon-notice')?.textContent).toBe('Statement imported.')
  })
  it('rejects bad CSV locally and shows API errors', async () => {
    const { f, calls } = api((m, u) => (m === 'POST' && u.endsWith('/reconciliation/runs') ? json({ code: 'idempotency_conflict', message: 'x' }, 409) : undefined))
    await load(f)
    await setInput(q('recon-account') as HTMLSelectElement, 'a1')
    await typeInto(q('recon-csv') as HTMLTextAreaElement, 'b1,bad,1')
    await click(q('recon-create'))
    expect(q('recon-create-error')?.textContent).toMatch(/YYYY/)
    expect(calls.some((c) => c.m === 'POST')).toBe(false)
    await typeInto(q('recon-csv') as HTMLTextAreaElement, 'b1,2026-01-02,1')
    await click(q('recon-create'))
    expect(q('recon-create-error')?.textContent).toMatch(/idempotency key/)
  })
  it('auto-matches, matches manually, unmatches and adds lines', async () => {
    const { f, calls } = api()
    await load(f)
    await open()
    await click(q('recon-automatch'))
    expect(calls.some((c) => c.m === 'POST' && c.url.includes('/runs/r1/match'))).toBe(true)
    await setInput(q('recon-pick-line') as HTMLSelectElement, 'l2')
    await setInput(q('recon-pick-entry') as HTMLSelectElement, 'e2')
    await click(q('recon-match'))
    expect(JSON.parse(calls.find((c) => c.url.endsWith('/runs/r1/matches'))!.body!)).toEqual({ line_id: 'l2', entry_id: 'e2' })
    await click(q('recon-unmatch'))
    expect(calls.some((c) => c.m === 'DELETE' && c.url.endsWith('/runs/r1/matches/m1'))).toBe(true)
    await typeInto(q('recon-add-csv') as HTMLTextAreaElement, 'b9,2026-01-05,-2.5')
    await click(q('recon-add-lines'))
    expect(JSON.parse(calls.find((c) => c.url.endsWith('/runs/r1/lines'))!.body!).lines[0].amount_minor).toBe(-250)
  })
  it('closes after confirmation and shows run_closed errors', async () => {
    const { f, calls } = api((m, u) => (m === 'POST' && u.endsWith('/close') ? json({ code: 'run_closed', message: 'x' }, 409) : undefined))
    await load(f)
    await open()
    await click(q('recon-close'))
    expect(calls.some((c) => c.url.endsWith('/close'))).toBe(false)
    await click(q('recon-close-yes'))
    expect(q('recon-error')?.textContent).toMatch(/closed/)
  })
  it('offers no actions on a closed run', async () => {
    const { f } = api(() => undefined, 'closed')
    await load(f)
    await open()
    expect(q('recon-close')).toBeNull()
    expect(q('recon-unmatch')).toBeNull()
  })
  it('has no axe violations', async () => {
    const { f } = api()
    const host = await load(f)
    await open()
    const res = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' ')}`)).toEqual([])
  })
})
