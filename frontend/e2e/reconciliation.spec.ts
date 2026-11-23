/** CP-6F/6I: Operate > Reconciliation. Import a statement, auto-match it against the ledger, close the run.
 *  The generated project's API is mocked (see preview-mock.ts) behind the preview sign-in; the project is real.
 *  Not run by its author; run with `npx playwright test e2e/reconciliation.spec.ts`. */
import { expect, test } from '@playwright/test'
import { createProjectViaApi, expectAxeClean, signedInUser, watchProblems } from './helpers'
import { BEARER, mockPreviewSession, signInPreview } from './preview-mock'

test('reconciliation: import a statement, auto-match, close the run', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Reconciliation Project')

  type Line = { id: string; line_no: number; external_id: string; date: string; amount_minor: number; currency: string; reference: string | null }
  const entry = { id: 'e1', date: '2026-11-03', amount_minor: 10000, reference: 'INV-7', description: 'Invoice INV-7' }
  let run: { id: string; account_id: string; currency: string; name: string | null; period_start: string | null; period_end: string | null; status: string; line_count: number; matched_count: number; summary: null } | null = null
  let lines: Line[] = []
  let matched = false
  const results = () => {
    const ml = matched ? lines.filter((l) => l.external_id === 'S-1') : []
    const ul = lines.filter((l) => !ml.includes(l))
    const ue = matched ? [] : [entry]
    const stmt = lines.reduce((s, l) => s + l.amount_minor, 0)
    const unl = ul.reduce((s, l) => s + l.amount_minor, 0)
    return {
      run: { ...run!, line_count: lines.length, matched_count: ml.length },
      matched: ml.map((l) => ({ match: { id: 'm1', method: 'auto', diff_minor: 0 }, line: l, entry })), matched_total: ml.length,
      unmatched_lines: ul, unmatched_entries: ue, entries_truncated: false,
      summary: { currency: 'USD', line_count: lines.length, matched_count: ml.length, unmatched_line_count: ul.length, unmatched_entry_count: ue.length, statement_total_minor: stmt, matched_diff_minor: 0, unmatched_lines_minor: unl, unmatched_entries_minor: ue.reduce((s, e) => s + e.amount_minor, 0), difference_minor: unl },
    }
  }
  const seen = await mockPreviewSession(page, id, (r) => {
    if (r.method === 'GET' && r.path === '/ledger/accounts') return { json: { items: [{ id: 'a1', code: '1000', name: 'Bank', currency: 'USD', exponent: 2 }], total: 1, limit: 200, offset: 0 } }
    if (r.method === 'GET' && r.path === '/reconciliation/runs') return { json: { items: run ? [{ ...run, line_count: lines.length, matched_count: matched ? 1 : 0 }] : [], total: run ? 1 : 0, limit: 100, offset: 0 } }
    if (r.method === 'POST' && r.path === '/reconciliation/runs') {
      const b = r.body as { account_id: string; name?: string; lines: { external_id: string; date: string; amount_minor: number; currency: string; reference?: string }[] }
      lines = b.lines.map((l, i) => ({ id: `l${i + 1}`, line_no: i + 1, external_id: l.external_id, date: l.date, amount_minor: l.amount_minor, currency: l.currency, reference: l.reference ?? null }))
      run = { id: 'run1', account_id: b.account_id, currency: 'USD', name: b.name ?? null, period_start: null, period_end: null, status: 'open', line_count: lines.length, matched_count: 0, summary: null }
      return { status: 201, json: run }
    }
    if (r.method === 'GET' && r.path === '/reconciliation/runs/run1/results') return { json: results() }
    if (r.method === 'POST' && r.path === '/reconciliation/runs/run1/match') { matched = true; return { json: { matched: 1 } } }
    if (r.method === 'POST' && r.path === '/reconciliation/runs/run1/close') { run!.status = 'closed'; return { json: run } }
    return undefined
  })
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/reconciliation`)
  await expect(page.getByRole('heading', { level: 1, name: 'Reconciliation' })).toBeVisible()
  expect(seen).toHaveLength(0)
  await signInPreview(page)
  await expect(page.getByTestId('recon-runs-empty')).toBeVisible()

  // Incomplete input is refused locally.
  await page.getByTestId('recon-create').click()
  await expect(page.getByTestId('recon-create-error')).toHaveText('Choose the ledger account the statement belongs to.')
  await page.getByTestId('recon-account').selectOption('a1')
  await page.getByTestId('recon-csv').fill('S-1,2026-11-03,100.00,USD,INV-7\nS-2,2026-11-04,25.00,USD,FEE')
  expect(seen.filter((s) => s.method === 'POST')).toHaveLength(0)
  await page.getByTestId('recon-name').fill('November')
  await page.getByTestId('recon-create').click()

  await expect(page.getByTestId('recon-notice')).toHaveText('Statement imported.')
  const created = seen.find((s) => s.method === 'POST' && s.path === '/reconciliation/runs')!
  expect(created.body).toMatchObject({ account_id: 'a1', name: 'November', lines: [{ external_id: 'S-1', date: '2026-11-03', amount_minor: 10000, currency: 'USD', reference: 'INV-7' }, { external_id: 'S-2', amount_minor: 2500 }] })
  await expect(page.getByTestId('recon-run-row')).toHaveCount(1)
  await expect(page.getByTestId('recon-detail')).toContainText('Run November (open)')
  await expect(page.getByTestId('recon-ul-row')).toHaveCount(2)
  await expect(page.getByTestId('recon-ue-row')).toHaveCount(1)
  await expect(page.getByTestId('recon-difference')).toHaveText('Difference (statement minus ledger): 125.00')

  // Auto-match pairs S-1 with the ledger entry; the 25.00 fee stays open.
  await page.getByTestId('recon-automatch').click()
  await expect(page.getByTestId('recon-notice')).toHaveText('Auto-match finished.')
  await expect(page.getByTestId('recon-pair')).toHaveCount(1)
  await expect(page.getByTestId('recon-pair')).toContainText('S-1')
  await expect(page.getByTestId('recon-pair')).toContainText('Invoice INV-7')
  await expect(page.getByTestId('recon-ul-row')).toHaveCount(1)
  await expect(page.getByTestId('recon-ue-empty')).toBeVisible()
  await expect(page.getByTestId('recon-difference')).toHaveText('Difference (statement minus ledger): 25.00')

  // Close asks first; closed runs offer no actions.
  await page.getByTestId('recon-close').click()
  await expect(page.getByTestId('recon-close-confirm')).toBeVisible()
  expect(seen.some((s) => s.path.endsWith('/close'))).toBe(false)
  await page.getByTestId('recon-close-yes').click()
  await expect(page.getByTestId('recon-notice')).toHaveText('Run closed.')
  await expect(page.getByTestId('recon-detail')).toContainText('Run November (closed)')
  await expect(page.getByTestId('recon-automatch')).toHaveCount(0)
  await expect(page.getByTestId('recon-close')).toHaveCount(0)
  expect(seen.every((s) => s.auth === BEARER)).toBe(true)

  await expectAxeClean(page, 'reconciliation page')
  watch.assertNone()
})
