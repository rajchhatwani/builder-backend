import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const project = '95ff34eb-4d07-4a60-8669-aaf1cf5442ca'
const run = '650a3687-da30-4199-8a69-ea345337918d'
const workspace = '700e83e8-4073-42a4-a8a4-54458f7bb71d'
const root = `/projects/${project}`
const zero = { total: 0, open: 0, covered: 0, out_of_scope: 0, percent_covered: 0, open_questions: 0 }
const emptyMap = { id: null, project_id: project, status: 'empty', items: [], questions: [], sources: [], phases: [], coverage: zero }
const map = {
  ...emptyMap, id: 'map', status: 'needs_answers',
  items: [
    { id: 'employee', kind: 'entity', text: 'Store each leave request with dates and a reason.', source_doc: 'leave-policy.pdf', source_page: 2,
      source_section: 'Leave requests', status: 'covered', covered_by: 'LeaveRequest', subject: 'Leave request' },
    { id: 'approve', kind: 'workflow', text: 'Send the request to the employee’s manager for approval.', status: 'open' },
  ],
  questions: [{ id: 'q', text: 'Who approves leave when a manager is away?', assumption: 'A department lead approves it.', state: 'open' }],
  sources: [{ name: 'leave-policy.pdf', kind: 'pdf', pages: 4, chunks: 2, chars: 5488 }],
  phases: [{ number: 1, name: 'Foundation', items: 1 }, { number: 2, name: 'Behaviour', items: 1 }],
  coverage: { ...zero, total: 2, open: 1, covered: 1, percent_covered: 50, open_questions: 1 },
}
const approval = {
  id: '98a826dd-0002-4ed3-9d0b-359875fec600', project_id: project, run_id: run, kind: 'A', subject: 'Approve the leave request plan',
  payload: {
    summary: 'Create a leave request workflow. Managers can review requests and record a decision.',
    plan: { entities: ['Employee', 'LeaveRequest'], hooks: ['notify_manager'], zones: ['leave-workflow'] },
  },
  risk_flags: ['auth'], requires_owner: true, state: 'pending', payload_hash: 'reviewed-plan-hash',
  bound_spec_hash: '7c1e51f7aefac40587ee', bound_commit: '6165418363ff4407b210e95960c693eaf1791ef7',
  expires_at: '2099-01-06T12:00:00Z', created_at: '2026-11-25T09:00:00Z', decision_note: null,
}
type Screen = 'intake' | 'plan'
type State = 'normal' | 'loading' | 'empty' | 'error'
const states: State[] = ['normal', 'loading', 'empty', 'error']
const screenshots: Record<State, (page: Page, screen: Screen) => Promise<void>> = {
  normal: (page, screen) => expect(page).toHaveScreenshot(`${screen}-normal.png`, { fullPage: true }),
  loading: (page, screen) => expect(page).toHaveScreenshot(`${screen}-loading.png`, { fullPage: true }),
  empty: (page, screen) => expect(page).toHaveScreenshot(`${screen}-empty.png`, { fullPage: true }),
  error: (page, screen) => expect(page).toHaveScreenshot(`${screen}-error.png`, { fullPage: true }),
}

async function mock(page: Page, screen: Screen, state: State, role = 'owner', changed = false) {
  const headers = {
    'access-control-allow-origin': 'http://localhost:5299',
    'access-control-allow-credentials': 'true',
    'access-control-allow-methods': 'GET, POST, PUT, OPTIONS',
    'access-control-allow-headers': 'content-type, authorization, x-requested-with',
  }
  const resource = screen === 'intake' ? `${root}/requirements` : `${root}/agent/approvals`
  let release = () => {}
  let read = false
  let decision: unknown
  let start: unknown
  let current = approval
  const paused = new Promise<void>(resolve => { release = resolve })
  await page.route(url => url.port === '8000' && (url.pathname.startsWith('/account/') || url.pathname === root || url.pathname.startsWith(`${root}/`)), async route => {
    const url = new URL(route.request().url())
    const method = route.request().method()
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers })
    const path = url.pathname
    const reply = (json: unknown) => route.fulfill({ status: 200, headers, json })
    if (path === resource && !read) {
      read = true
      if (state === 'loading') await paused
      if (state === 'error') return route.fulfill({ status: 500, headers, json: { code: 'fixture', message: 'Fixture request failed.', details: [] } })
    }
    if (path === '/account/refresh') return reply({ access_token: 'fixture' })
    if (path === '/account/me') return reply({ id: 'user', platform_role: 'customer', email_verified_at: '2026-11-01T00:00:00Z' })
    // Guided screens stay usable with the project ID when metadata is unavailable.
    if (path === root) return route.fulfill({ status: 503, headers, json: { code: 'fixture', details: [] } })
    if (path === `${root}/status`) return reply({ sections: [] })
    if (path === `${root}/members`) return reply([{ user_id: 'user', name: 'Pat Reviewer', role }])
    if (path === `${root}/workspaces`) return reply([{ id: workspace, name: 'Review workspace', state: 'active' }])
    if (path === `${root}/requirements`) return reply(state === 'empty' ? emptyMap : map)
    if (path === `${root}/requirements/start-run`) {
      start = route.request().postDataJSON()
      return reply({ id: run })
    }
    if (path === `${root}/agent/approvals`) return reply(state === 'empty' ? [] : [current])
    if (path.endsWith(`/approvals/${approval.id}`)) return reply(changed ? { ...current, bound_commit: 'changed-commit' } : current)
    if (path.endsWith(`/approvals/${approval.id}/decision`)) {
      decision = route.request().postDataJSON()
      current = { ...current, state: 'approved' }
      return reply(current)
    }
    return route.fulfill({ status: 404, headers, json: { code: 'fixture_missing', message: 'No fixture for request.', details: [] } })
  })
  return { release, decision: () => decision, start: () => start }
}

test.use({ timezoneId: 'UTC' })

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('v2-language', 'en'))
  await page.clock.setFixedTime(new Date('2026-11-25T12:00:00Z'))
})

for (const screen of ['intake', 'plan'] as const) {
  for (const state of states) {
    test(`${screen} ${state}`, async ({ page }) => {
      const fixture = await mock(page, screen, state)
      try {
        await page.goto(`${root}/${screen}`)
        await expect(page.getByRole('heading', { name: screen === 'intake' ? 'Describe what you want built' : 'Review the plan' })).toBeVisible()
        await expect(page.getByText('We could not load this project.', { exact: true })).toHaveCount(0)
        if (state === 'normal') {
          await expect(page.getByTestId(screen === 'intake' ? 'start-build' : 'plan-approve')).toBeEnabled()
          if (screen === 'intake') await expect(page.getByRole('combobox', { name: 'Workspace' })).toBeEnabled()
        }
        if (state === 'loading') await expect(page.getByRole('status', { name: screen === 'intake' ? 'Loading requirements…' : 'Loading plan…' })).toBeVisible()
        if (state === 'empty') await expect(page.getByRole(screen === 'intake' ? 'button' : 'link', { name: screen === 'intake' ? 'Write your request' : 'Describe your app' })).toBeVisible()
        if (state === 'error') await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
        await page.evaluate(() => document.fonts.ready.then(() => undefined))
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(await page.evaluate(() => window.innerWidth))
        const result = await new AxeBuilder({ page }).analyze()
        expect(result.violations.map(({ id, nodes }) => ({ id, targets: nodes.map(node => node.target) }))).toEqual([])
        await screenshots[state](page, screen)
        if (state === 'error') {
          await page.getByRole('button', { name: 'Try again' }).click()
          await expect(page.getByTestId(screen === 'intake' ? 'requirements-map' : 'plan-card')).toBeVisible()
        }
      } finally {
        fixture.release()
      }
    })
  }
}

test('starts the selected phase in the selected workspace after confirming assumptions', async ({ page }) => {
  const fixture = await mock(page, 'intake', 'normal')
  await page.goto(`${root}/intake?phase=2&workspace=${workspace}`)
  await expect(page.getByRole('combobox', { name: 'Workspace' })).toContainText('Review workspace')
  await page.getByTestId('start-build').click()
  const dialog = page.getByRole('dialog', { name: 'Confirm assumptions' })
  await expect(dialog).toBeVisible()
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
  expect(fixture.start()).toBeUndefined()
  await dialog.getByRole('button', { name: 'Accept assumptions and start' }).click()
  await expect(page).toHaveURL(`${root}/build?run=${run}`)
  expect(fixture.start()).toEqual({ phase: 2, workspace_id: workspace, accept_assumptions: true })
})

test('presents both screens read-only to a viewer', async ({ page }) => {
  await mock(page, 'intake', 'normal', 'viewer')
  await page.goto(`${root}/intake`)
  await expect(page.getByText('You can look at this but not change it. Your role is viewer.')).toBeVisible()
  await expect(page.getByTestId('intake-submit')).toHaveCount(0)
  await mock(page, 'plan', 'normal', 'viewer')
  await page.goto(`${root}/plan`)
  await expect(page.getByTestId('plan-gate-reason')).toContainText('Viewers can read approvals')
  await expect(page.getByTestId('plan-approve')).toHaveCount(0)
})

test('stops a decision when the reviewed binding changes', async ({ page }) => {
  const fixture = await mock(page, 'plan', 'normal', 'owner', true)
  await page.goto(`${root}/plan?run=${run}`)
  await page.getByTestId('plan-approve').click()
  await expect(page.getByTestId('plan-changed')).toBeVisible()
  await expect(page.getByText('changed-commit')).toBeVisible()
  expect(fixture.decision()).toBeUndefined()
})
