/** CP-6G: Operate > Agent runs: registry, stats and starting a dry run.
 *  The generated project's API is mocked (see preview-mock.ts) behind the preview sign-in; the project is real.
 *  Not run by its author; run with `npx playwright test e2e/agentruns.spec.ts`. */
import { expect, test } from '@playwright/test'
import { createProjectViaApi, expectAxeClean, signedInUser, watchProblems } from './helpers'
import { BEARER, mockPreviewSession, signInPreview } from './preview-mock'

const REG = {
  agents: [{ name: 'scribe', stage: 'answer', autonomy: 'suggest', actions: ['note'], max_actions_per_run: 5, require_eval: null, eval_ready: null }],
  actions: [{ name: 'note', kind: 'note', description: 'Write a note', risk: 'low', max_autonomy: 'auto', entity: null, fields: [] }],
}
const STAT = { agent: 'scribe', runs: 4, proposals: 6, executed: 1, rejected: 2, pending: 3, outcome_success: 1, outcome_failure: 0, outcome_neutral: 0, success_rate_bp: 10000 }
const PROP = { id: 'p1', action: 'note', kind: 'note', risk: 'low', args: { text: 'hello' }, allowed_autonomy: 'suggest', status: 'suggested', reason: null, result: null, error_code: null }
const RUN = { id: 'r1', agent: 'scribe', goal: 'Summarise today', mode: 'suggest', effective_autonomy: 'suggest', status: 'completed', error_code: null, started_by: null, created_at: '2026-01-01', proposals: [PROP] }

test('agent runs: registry, stats and a dry run', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Agent Runs Project')

  const seen = await mockPreviewSession(page, id, (r) => {
    if (r.method === 'GET' && r.path === '/ai/agents') return { json: REG }
    if (r.method === 'GET' && r.path === '/ai/agents/stats') return { json: { agents: [STAT] } }
    if (r.method === 'GET' && r.path === '/ai/agents/runs') return { json: { items: [], total: 0 } }
    if (r.method === 'POST' && r.path === '/ai/agents/scribe/runs') return { status: 201, json: RUN }
    return undefined
  })
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/agentruns`)
  await expect(page.getByRole('heading', { level: 1, name: 'Agent runs' })).toBeVisible()
  expect(seen).toHaveLength(0)
  await signInPreview(page)

  await expect(page.getByTestId('registry-agent')).toContainText('scribe')
  await expect(page.getByTestId('stats-row')).toContainText('scribe')

  await page.getByTestId('start-run').click()
  await expect(page.getByTestId('start-error')).toHaveText('Choose an agent.')
  await page.getByTestId('start-agent').selectOption('scribe')
  await page.getByTestId('start-goal').fill('Summarise today')
  await page.getByTestId('start-run').click()
  await expect(page.getByTestId('start-ok')).toBeVisible()
  await expect(page.getByTestId('run-status')).toHaveText('completed')
  await expect(page.getByTestId('run-proposal')).toHaveCount(1)
  const started = seen.find((s) => s.method === 'POST' && s.path === '/ai/agents/scribe/runs')!
  expect(started.body).toMatchObject({ goal: 'Summarise today', mode: 'suggest' })
  expect(seen.every((s) => s.auth === BEARER)).toBe(true)

  await expectAxeClean(page, 'agent runs page')
  watch.assertNone()
})
