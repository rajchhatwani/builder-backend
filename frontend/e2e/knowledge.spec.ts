/** CP-6G: Operate > Knowledge: add a source, search it and ask a question.
 *  The generated project's API is mocked (see preview-mock.ts) behind the preview sign-in; the project is real.
 *  Not run by its author; run with `npx playwright test e2e/knowledge.spec.ts`. */
import { expect, test } from '@playwright/test'
import { createProjectViaApi, expectAxeClean, signedInUser, watchProblems } from './helpers'
import { BEARER, mockPreviewSession, signInPreview } from './preview-mock'

const SRC = { id: 's1', title: 'Handbook', allowed_roles: ['admin'], owner_only: false, owner_id: 'abcdef123', chunk_count: 3, created_at: '2026-01-01' }

test('knowledge: sources, search and ask', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Knowledge Project')

  const seen = await mockPreviewSession(page, id, (r) => {
    if (r.method === 'GET' && r.path === '/ai/knowledge/sources') return { json: { items: [SRC], total: 1 } }
    if (r.method === 'POST' && r.path === '/ai/knowledge/sources') return { status: 201, json: { ...SRC, id: 's2', title: 'Policy' } }
    if (r.method === 'POST' && r.path === '/ai/knowledge/search') return { json: { hits: [{ source_id: 's1', chunk_id: 'c1', title: 'Handbook', text: 'Refunds take 5 days.', position: 0, score_bp: 8750 }] } }
    if (r.method === 'POST' && r.path === '/ai/knowledge/ask') return { json: { answer: 'Five days.', grounded: true, citations: [{ source_id: 's1', chunk_id: 'c1', title: 'Handbook', quote: 'Refunds take 5 days.', score_bp: 9000 }], call_id: null } }
    return undefined
  })
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/knowledge`)
  await expect(page.getByRole('heading', { level: 1, name: 'Knowledge library' })).toBeVisible()
  expect(seen).toHaveLength(0)
  await signInPreview(page)

  await expect(page.getByTestId('source-row')).toHaveCount(1)
  await expect(page.getByTestId('source-row')).toContainText('Handbook')

  await page.getByTestId('source-create').click()
  await expect(page.getByTestId('source-create-error')).toHaveText('Enter a title.')
  await page.getByTestId('source-title').fill('Policy')
  await page.getByTestId('source-text').fill('Returns are free.')
  await page.getByTestId('source-roles').fill('admin, staff')
  await page.getByTestId('source-create').click()
  await expect(page.getByTestId('source-notice')).toHaveText('Source added.')
  expect(seen.find((s) => s.method === 'POST' && s.path === '/ai/knowledge/sources')!.body).toEqual({ title: 'Policy', text: 'Returns are free.', allowed_roles: ['admin', 'staff'] })

  await page.getByTestId('search-query').fill('refunds')
  await page.getByTestId('search-run').click()
  await expect(page.getByTestId('search-hit')).toContainText('Refunds take 5 days.')
  expect(seen.find((s) => s.path === '/ai/knowledge/search')!.body).toEqual({ query: 'refunds', limit: 5 })

  await page.getByTestId('ask-question').fill('How long do refunds take?')
  await page.getByTestId('ask-run').click()
  await expect(page.getByTestId('ask-answer')).toHaveText('Five days.')
  await expect(page.getByTestId('ask-citation')).toHaveCount(1)
  expect(seen.find((s) => s.path === '/ai/knowledge/ask')!.body).toEqual({ question: 'How long do refunds take?', limit: 4 })
  expect(seen.every((s) => s.auth === BEARER)).toBe(true)

  await expectAxeClean(page, 'knowledge page')
  watch.assertNone()
})
