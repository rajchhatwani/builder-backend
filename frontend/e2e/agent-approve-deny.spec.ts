/** FB4-b: the approval decision end to end. The e2e stack has no scripted model, so a run waiting on a person is
 *  seeded in the database (helpers.seedPendingApproval); everything after that is the real UI and the real API. */
import { expect, test } from '@playwright/test'
import { createProjectViaApi, seedPendingApproval, signedInUser, watchProblems } from './helpers'

const WEB = process.env.E2E_WEB_PORT ?? '5199'
test.use({
  storageState: { cookies: [], origins: [{ origin: `http://localhost:${WEB}`, localStorage: [{ name: 'ui.shell', value: 'v2' }] }] },
})

async function waitingRun(page: Parameters<typeof signedInUser>[0], request: Parameters<typeof signedInUser>[1], kind: 'B' | 'D', subject: string, payload: Record<string, unknown>, flags: string[] = []) {
  const api = await signedInUser(page, request)
  const projectId = await createProjectViaApi(api, `Approve ${kind}`)
  const created = await api.post(`/projects/${projectId}/agent/runs`, { goal: 'Seeded approval check' })
  expect(created.status(), await created.text()).toBe(201)
  const run = await created.json()
  const approvalId = seedPendingApproval(run.id, projectId, kind, subject, payload, flags)
  return { api, projectId, approvalId }
}
const state = async (api: Awaited<ReturnType<typeof signedInUser>>, projectId: string, id: string) =>
  (await (await api.get(`/projects/${projectId}/agent/approvals/${id}`)).json()).state

test('approve: inbox, review, Approve records the decision', async ({ page, request }) => {
  const { api, projectId, approvalId } = await waitingRun(page, request, 'B', 'Keep the new Invoice entity', { summary: 'Added invoices', files: ['spec.json'] })
  const watch = watchProblems(page)
  await page.goto(`/#/p/${projectId}/approvals`)
  await expect(page.getByTestId('approval-row')).toHaveCount(1)
  await page.getByTestId('row-open').click()
  await expect(page.getByTestId('review-summary')).toHaveText('Added invoices')
  await page.getByTestId('review-approve').click()
  await expect(page.getByTestId('review-done')).toContainText('Approved')
  await expect(page.getByTestId('review-approve')).toHaveCount(0)
  expect(await state(api, projectId, approvalId)).toBe('approved')
  watch.assertNone()
})

test('deny: a reason is required, then Deny records it', async ({ page, request }) => {
  const { api, projectId, approvalId } = await waitingRun(page, request, 'B', 'Drop the audit table', { summary: 'Removes a table' })
  await page.goto(`/#/p/${projectId}/approvals?approval=${approvalId}`)
  await page.getByTestId('review-deny').click()
  await expect(page.getByTestId('note-help')).toContainText('Say why')
  expect(await state(api, projectId, approvalId)).toBe('pending')
  await page.getByTestId('review-note').fill('too broad')
  await page.getByTestId('review-deny').click()
  await expect(page.getByTestId('review-done')).toContainText('Denied')
  expect(await state(api, projectId, approvalId)).toBe('denied')
})

test('Gate D: Approve stays disabled until the affected name is typed', async ({ page, request }) => {
  const { api, projectId, approvalId } = await waitingRun(page, request, 'D', 'Remove entity Invoice', { op_type: 'remove_entity', name: 'Invoice' }, ['data_deletion'])
  await page.goto(`/#/p/${projectId}/approvals?approval=${approvalId}`)
  await expect(page.getByTestId('gate-d-headline')).toHaveText('Remove the entity Invoice')
  await expect(page.getByTestId('review-approve')).toBeDisabled()
  await page.getByTestId('review-confirm').fill('Invoice')
  await expect(page.getByTestId('review-approve')).toBeEnabled()
  await page.getByTestId('review-approve').click()
  await expect(page.getByTestId('review-done')).toContainText('Approved')
  expect(await state(api, projectId, approvalId)).toBe('approved')
})
