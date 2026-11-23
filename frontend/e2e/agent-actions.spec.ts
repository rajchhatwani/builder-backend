/** F5-5: Operate > AI actions (new shell). Approve one agent proposal, reject another with a reason, record an outcome.
 *  The project API is mocked (see preview-mock.ts). Not run by its author; run with `npx playwright test e2e/agent-actions.spec.ts`. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { createProjectViaApi, signedInUser, watchProblems } from './helpers'
import { BEARER, SESSION, mockPreviewSession, signInPreview } from './preview-mock'

test('agent actions: approve one proposal, reject another, mark the outcome', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Agent Actions Project')

  type P = { id: string; run_id: string; agent: string; action: string; kind: string; risk: string; args: Record<string, unknown>; allowed_autonomy: string; status: string; reason: string | null; result: unknown; error_code: string | null; outcome: string | null }
  const mk = (pid: string, action: string, risk: string, args: Record<string, unknown>): P => ({ id: pid, run_id: 'run1', agent: 'triage', action, kind: 'entity_create', risk, args, allowed_autonomy: 'auto', status: 'pending_approval', reason: null, result: null, error_code: null, outcome: null })
  const props: P[] = [mk('p1', 'create_ticket', 'high', { title: 'Refund order 1042', amount_minor: 2500 }), mk('p2', 'send_email', 'medium', { to: 'ops@example.com' })]
  const seen = await mockPreviewSession(page, id, (r) => {
    if (r.method === 'GET' && r.path === '/ai/agents/stats') {
      return { json: { agents: [{ agent: 'triage', runs: 2, proposals: 2, executed: 0, rejected: 0, pending: 2, outcome_success: 0, outcome_failure: 0, outcome_neutral: 0, success_rate_bp: null }] } }
    }
    if (r.method === 'GET' && r.path === '/ai/agents/proposals') {
      const st = new URLSearchParams(r.search).get('status')
      const items = props.filter((p) => p.status === st)
      return { json: { items, total: items.length, limit: 20, offset: 0 } }
    }
    if (r.method === 'GET' && r.path === '/ai/agents/runs/run1') return { json: { id: 'run1', agent: 'triage', goal: 'Triage the support inbox', status: 'completed' } }
    const m = /^\/ai\/agents\/proposals\/([^/]+)\/(approve|reject|outcome)$/.exec(r.path)
    if (r.method === 'POST' && m) {
      const p = props.find((x) => x.id === m[1])
      if (!p) return { status: 404, json: { code: 'not_found', message: 'no' } }
      if (m[2] === 'approve') { p.status = 'executed'; p.result = { ok: true } }
      if (m[2] === 'reject') { p.status = 'rejected'; p.reason = (r.body as { reason?: string } | null)?.reason ?? null }
      if (m[2] === 'outcome') p.outcome = (r.body as { outcome: string }).outcome
      return { json: p }
    }
    return undefined
  })
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/agentactions`)
  await expect(page.getByTestId('agentapprovals-page')).toBeVisible()
  expect(seen).toHaveLength(0)
  await signInPreview(page)

  await expect(page.getByTestId('agentapprovals-live')).toHaveText('2 Pending approval proposals, showing 1 to 2.')
  expect(seen.find((s) => s.path === '/ai/agents/proposals')!.search).toBe('?status=pending_approval&limit=20&offset=0')
  await expect(page.getByTestId('agent-rate-triage')).toHaveText('no outcomes yet')
  await expect(page.getByTestId('proposal-head-p1')).toHaveText('triage proposes create_ticket')
  await expect(page.getByTestId('proposal-risk-p1')).toHaveText('High risk')
  await expect(page.getByTestId('proposal-args-p1')).toContainText('"title": "Refund order 1042"')
  await page.getByTestId('run-link-p1').click()
  await expect(page.getByTestId('run-goal-p1')).toHaveText('Goal: Triage the support inbox')

  // Approve p1.
  await page.getByTestId('approve-p1').click()
  await expect(page.getByTestId('agentapprovals-notice')).toHaveText('create_ticket: approved.')
  const appr = seen.filter((s) => s.method === 'POST' && s.path === '/ai/agents/proposals/p1/approve')
  expect(appr).toHaveLength(1)
  expect(appr[0].body).toEqual({})
  await expect(page.getByTestId('proposal-p1')).toHaveCount(0)
  await expect(page.getByTestId('agentapprovals-live')).toHaveText('1 Pending approval proposal, showing 1 to 1.')

  // Reject p2 with a reason.
  await page.getByTestId('reject-p2').click()
  await expect(page.getByTestId('form-reject-p2')).toBeVisible()
  await page.getByTestId('agentapprovals-text').fill('Not now')
  await page.getByTestId('confirm-reject').click()
  await expect(page.getByTestId('agentapprovals-notice')).toHaveText('send_email: rejected.')
  const rej = seen.find((s) => s.method === 'POST' && s.path === '/ai/agents/proposals/p2/reject')!
  expect(rej.body).toEqual({ reason: 'Not now' })
  await expect(page.getByTestId('agentapprovals-empty')).toBeVisible()

  // The executed one can be judged afterwards.
  await page.getByTestId('agentapprovals-status').selectOption('executed')
  await expect(page.getByTestId('proposal-p1')).toBeVisible()
  await page.getByTestId('outcome-success-p1').click()
  await expect(page.getByTestId('agentapprovals-notice')).toHaveText('create_ticket: outcome recorded as worked.')
  expect(seen.find((s) => s.method === 'POST' && s.path === '/ai/agents/proposals/p1/outcome')!.body).toEqual({ outcome: 'success' })
  await expect(page.getByTestId('proposal-outcome-p1')).toHaveText('Outcome: Worked')
  expect(seen.filter((s) => s.method === 'POST')).toHaveLength(3)
  expect(seen.every((s) => s.auth === BEARER && s.previewToken === SESSION.previewToken && !s.search.includes(SESSION.jwt))).toBe(true)

  const axe = await new AxeBuilder({ page }).analyze()
  expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), 'axe on the AI actions page').toEqual([])
  watch.assertNone()
})
