/** CP-6G: Operate > AI evals: run a suite (dry) and read the results.
 *  The generated project's API is mocked (see preview-mock.ts) behind the preview sign-in; the project is real.
 *  Not run by its author; run with `npx playwright test e2e/evals.spec.ts`. */
import { expect, test } from '@playwright/test'
import { createProjectViaApi, expectAxeClean, signedInUser, watchProblems } from './helpers'
import { BEARER, mockPreviewSession, signInPreview } from './preview-mock'

const RUN = { id: 'r1', suite: 'triage', agent: 'helper', score_bp: 5000, passed: false, total: 2, passed_count: 1, created_by: null, created_at: '2026-01-02',
  results: [{ case: 'good case', passed: true, proposed: ['note'], error_code: null }, { case: 'bad case', passed: false, proposed: [], error_code: 'budget_exceeded' }] }
const SUITE = { name: 'triage', agent: 'helper', pass_bp: 8000, case_count: 2, latest: null }

test('evals: run a suite and see pass/fail per case', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Evals Project')

  const seen = await mockPreviewSession(page, id, (r) => {
    if (r.method === 'GET' && r.path === '/ai/evals/suites') return { json: [SUITE] }
    if (r.method === 'GET' && r.path === '/ai/evals/runs') return { json: { items: [], total: 0 } }
    if (r.method === 'POST' && r.path === '/ai/evals/suites/triage/run') return { status: 201, json: RUN }
    return undefined
  })
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/evals`)
  await expect(page.getByRole('heading', { level: 1, name: 'AI evals' })).toBeVisible()
  expect(seen).toHaveLength(0)
  await signInPreview(page)

  await expect(page.getByTestId('evals-dry-note')).toContainText('dry')
  await expect(page.getByTestId('suite-row')).toContainText('Never run')
  await page.getByTestId('suite-run').click()
  await expect(page.getByTestId('eval-verdict')).toHaveText('Suite failed')
  await expect(page.getByTestId('eval-case')).toHaveCount(2)
  await expect(page.getByTestId('eval-case').nth(1)).toContainText('Error: budget_exceeded')
  expect(seen.some((s) => s.method === 'POST' && s.path === '/ai/evals/suites/triage/run')).toBe(true)
  expect(seen.every((s) => s.auth === BEARER)).toBe(true)

  await expectAxeClean(page, 'evals page')
  watch.assertNone()
})
