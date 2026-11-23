/** CP-6G: Operate > AI usage: gateway budget totals and the calls table with its filters.
 *  The generated project's API is mocked (see preview-mock.ts) behind the preview sign-in; the project is real.
 *  Not run by its author; run with `npx playwright test e2e/aiusage.spec.ts`. */
import { expect, test } from '@playwright/test'
import { createProjectViaApi, expectAxeClean, signedInUser, watchProblems } from './helpers'
import { BEARER, mockPreviewSession, signInPreview } from './preview-mock'

const USAGE = { period: 'day', period_start: '2026-01-01', limit_micro_usd: 1_000_000, spent_micro_usd: 250_000, reserved_micro_usd: 50_000, remaining_micro_usd: 700_000, calls_ok: 3, calls_error: 1, input_tokens: 100, output_tokens: 40, zero_retention: true, region: 'eu' }
const CALL = { id: 'abcdef12-0000', caller_id: null, stage: 'answer', provider: 'fake', model: 'm1', status: 'ok', input_tokens: 10, output_tokens: 5, cost_micro_usd: 1234, reserved_micro_usd: 2000, error_code: null, fallback_used: false, created_at: '2026-01-01T00:00:00Z', finished_at: null }

test('ai usage: totals, calls and filters', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'AI Usage Project')

  const seen = await mockPreviewSession(page, id, (r) => {
    if (r.method !== 'GET') return undefined
    if (r.path === '/ai/usage') return { json: USAGE }
    if (r.path === '/ai/calls') return { json: { items: [CALL], total: 1, limit: 50, offset: 0 } }
    return undefined
  })
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/aiusage`)
  await expect(page.getByRole('heading', { level: 1, name: 'AI usage' })).toBeVisible()
  expect(seen).toHaveLength(0)
  await signInPreview(page)

  await expect(page.getByTestId('usage-spent')).toHaveText('USD 0.250000')
  await expect(page.getByTestId('usage-remaining')).toHaveText('USD 0.700000')
  await expect(page.getByTestId('usage-calls')).toHaveText('3 / 1')
  await expect(page.getByTestId('calls-row')).toHaveCount(1)
  await expect(page.getByTestId('calls-row')).toContainText('0.001234')

  await page.getByTestId('calls-stage').fill('answer')
  await page.getByTestId('calls-status').selectOption('ok')
  await expect.poll(() => seen.some((s) => s.path === '/ai/calls' && s.search.includes('stage=answer') && s.search.includes('status=ok'))).toBe(true)
  expect(seen.every((s) => s.auth === BEARER)).toBe(true)

  await expectAxeClean(page, 'ai usage page')
  watch.assertNone()
})
