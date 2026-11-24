import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const project = '95ff34eb-4d07-4a60-8669-aaf1cf5442ca'
const run = '650a3687-da30-4199-8a69-ea345337918d'
const workspace = '700e83e8-4073-42a4-a8a4-54458f7bb71d'
const preview = '98a826dd-0002-4ed3-9d0b-359875fec600'
const approval = '94c826dd-0002-4ed3-9d0b-359875fec601'
const root = '/projects/' + project
const date = '2026-11-25T10:00:00Z'
const build = {
  id: run, project_id: project, workspace_id: workspace, goal: 'Build employee leave requests',
  state: 'awaiting_approval', phase: 'build', budgets: { max_steps: 60, max_repairs: 3, max_cost_micro_usd: 1_500_000 },
  steps_used: 7, repairs_used: 1, cost_micro_usd: 130_000, started_at: date, updated_at: date,
  steps: [{ id: 'step', seq: 1, kind: 'tool', tool_name: 'add_entity', state: 'complete', ok: true, output: { cost_micro_usd: 3000 } }],
  steps_total: 1, limit: 200, offset: 0,
}
const request = {
  id: approval, run_id: run, project_id: project, kind: 'B', subject: 'Add request status to LeaveRequest',
  payload: { summary: 'Managers can see the review state of each leave request.' }, risk_flags: ['auth'],
  state: 'pending', requires_owner: true, bound_spec_hash: 'spec', bound_commit: 'commit', payload_hash: 'payload',
  expires_at: '2099-01-01T12:00:00Z', created_at: date,
}
const instance = {
  id: preview, project_id: project, workspace_id: null, state: 'running', is_preview: true, spec_hash: 'preview-spec',
  url_path: '/previews/' + preview + '/', expires_at: '2099-01-01T12:00:00Z', created_at: date, last_request_at: date,
  limits: { sleep_after_minutes: 15, rate_per_minute: 30 },
}
const operation = { responses: { 200: { description: 'OK' } } }
const body = { requestBody: { content: { 'application/json': { schema: { type: 'object', properties: { name: { type: 'string' } }, required: ['name'] } } } } }
const spec = { openapi: '3.0.0', paths: {
  '/leave-requests': { get: operation, post: { ...operation, ...body } },
  '/leave-requests/{id}': {
    parameters: [{ name: 'id', in: 'path', required: true, schema: { type: 'integer' } }],
    get: operation, patch: { ...operation, ...body },
  },
} }
type Screen = 'build' | 'approvals' | 'see'
type State = 'normal' | 'loading' | 'empty' | 'error'
const resources = { build: root + '/agent/runs', approvals: root + '/agent/approvals', see: root + '/previews' }
const title = { build: 'Build progress', approvals: 'Approvals', see: 'See it work' }
const loading = { build: 'Loading build…', approvals: 'Loading approvals…', see: 'Loading previews…' }
const empty = { build: 'No build has started yet.', approvals: 'Nothing is waiting for you.', see: 'No preview is running for this source.' }
const screenshots: Record<State, (page: Page, screen: Screen) => Promise<void>> = {
  normal: (page, screen) => expect(page).toHaveScreenshot(screen + '-normal.png', { fullPage: true }),
  loading: (page, screen) => expect(page).toHaveScreenshot(screen + '-loading.png', { fullPage: true }),
  empty: (page, screen) => expect(page).toHaveScreenshot(screen + '-empty.png', { fullPage: true }),
  error: (page, screen) => expect(page).toHaveScreenshot(screen + '-error.png', { fullPage: true }),
}

async function mock(page: Page, screen: Screen, state: State, role = 'owner') {
  await page.addInitScript(() => localStorage.setItem('v2-language', 'en'))
  await page.clock.setFixedTime(new Date('2026-11-25T12:00:00Z'))
  const headers = {
    'access-control-allow-origin': 'http://localhost:5299',
    'access-control-allow-credentials': 'true',
    'access-control-allow-methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
    'access-control-allow-headers': 'content-type, authorization, x-requested-with, x-preview-token',
  }
  let release = () => {}
  const block = new Promise<void>(resolve => { release = resolve })
  const writes: { path: string; body: unknown; access?: string }[] = []
  let first = true
  let started = false
  let activeBuild = build
  let activeRequest = request
  await page.route(url => url.port === '8000', async route => {
    const call = route.request()
    const path = new URL(call.url()).pathname
    const method = call.method()
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers })
    const send = (json: unknown, status = 200) => route.fulfill({ status, headers, json })
    if (method !== 'GET') writes.push({ path, body: call.postData() ? call.postDataJSON() : null, access: call.headers()['x-preview-token'] })
    if (first && path === resources[screen] && method === 'GET') {
      first = false
      if (state === 'loading') await block
      if (state === 'error') return send({ code: 'fixture_failure', message: 'Fixture request failed.', details: [] }, 500)
    }
    if (path === '/account/me') return send({ id: 'user', platform_role: 'customer', email_verified_at: date })
    if (path === root) return send({ id: project, organization_id: null })
    if (path === root + '/status') return send({ sections: [] })
    if (path === root + '/members') return send([{ user_id: 'user', name: 'Pat Reviewer', role }])
    if (path === root + '/workspaces') return send([{ id: workspace, name: 'Leave requests', state: 'active' }])
    if (path === resources.build) return send({ items: state === 'empty' ? [] : [activeBuild], total: state === 'empty' ? 0 : 1, limit: 20, offset: 0 })
    if (path === resources.build + '/' + run) return send(activeBuild)
    if (path.endsWith('/cancel')) {
      activeBuild = { ...activeBuild, state: 'cancelled' }
      return send(activeBuild)
    }
    if (path === resources.approvals) return send(state === 'empty' ? [] : [activeRequest])
    if (path === resources.approvals + '/' + approval) return send(activeRequest)
    if (path.endsWith('/decision')) {
      activeRequest = { ...request, state: 'approved' }
      return send(activeRequest)
    }
    if (path === resources.see) {
      if (method === 'POST') {
        started = true
        return send({ ...instance, token: 'preview-fixture-token' }, 201)
      }
      return send(started || state !== 'empty' ? [instance] : [])
    }
    if (path === resources.see + '/' + preview) return send(instance)
    if (path.endsWith('/rotate-token')) return send({ ...instance, token: 'preview-fixture-token' })
    if (path === '/previews/' + preview + '/openapi.json') return send(spec)
    if (path === '/previews/' + preview + '/leave-requests') return method === 'POST' ? send({ id: 7 }, 201) : send([])
    if (path === '/previews/' + preview + '/leave-requests/7') return send({ id: 7 })
    return send({ code: 'fixture_missing', message: 'No fixture for request.', details: [] }, 404)
  })
  return { release, writes }
}

test.use({ timezoneId: 'UTC' })

for (const screen of ['build', 'approvals', 'see'] as const) {
  for (const state of ['normal', 'loading', 'empty', 'error'] as const) {
    test(screen + ' ' + state, async ({ page }) => {
      const fixture = await mock(page, screen, state)
      try {
        await page.goto(root + '/' + screen)
        await expect(page.getByRole('heading', { name: title[screen], exact: true })).toBeVisible()
        if (state === 'loading') await expect(page.getByRole('status', { name: loading[screen] })).toBeVisible()
        if (state === 'empty') {
          await expect(page.getByRole('heading', { name: empty[screen] })).toBeVisible()
          if (screen === 'build') await expect(page.getByRole('heading', { name: 'Leave requests', exact: true })).toBeVisible()
        }
        if (screen === 'build') await expect(page.getByRole('button', { name: 'Start a run' })).toBeVisible()
        if (state === 'error') await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
        if (state === 'normal') {
          if (screen === 'see') {
            await page.getByRole('button', { name: 'Issue a new token' }).click()
            await page.getByRole('dialog').getByRole('button', { name: 'Confirm' }).click()
            await expect(page.getByRole('dialog')).toHaveCount(0)
            await expect(page.getByRole('button', { name: 'Run all four checks' })).toBeEnabled()
          }
          if (screen === 'build') await expect(page.getByTestId('run-cancel')).toBeVisible()
          if (screen === 'approvals') await expect(page.getByRole('link', { name: request.subject })).toBeVisible()
        }
        if (state !== 'loading') await expect(page.getByText('Read-only', { exact: true })).toHaveCount(0)
        await page.evaluate(() => document.fonts.ready.then(() => undefined))
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(await page.evaluate(() => window.innerWidth))
        const result = await new AxeBuilder({ page }).analyze()
        expect(result.violations.map(({ id, nodes }) => ({ id, targets: nodes.map(node => node.target) }))).toEqual([])
        await screenshots[state](page, screen)
      } finally { fixture.release() }
    })
  }
}

test('confirms before cancelling the draft', async ({ page }) => {
  const fixture = await mock(page, 'build', 'normal')
  await page.goto(root + '/build')
  await page.getByTestId('run-cancel').click()
  const dialog = page.getByRole('dialog', { name: 'Cancel this run?' })
  await expect(dialog).toContainText('its draft is discarded')
  expect(fixture.writes).toEqual([])
  await dialog.getByRole('button', { name: 'Cancel run' }).click()
  await expect(page.getByText('Cancelled', { exact: true })).toBeVisible()
  expect(fixture.writes.map(write => write.path)).toEqual([resources.build + '/' + run + '/cancel'])
})

test('blocks viewer writes to builds and approval reviews', async ({ page }) => {
  await mock(page, 'build', 'normal', 'viewer')
  await page.goto(root + '/build')
  await expect(page.getByTestId('build-run')).toBeVisible()
  await expect(page.getByTestId('run-cancel')).toHaveCount(0)
  await page.goto(root + '/approvals?approval=' + approval)
  await expect(page.getByRole('heading', { name: request.subject })).toBeVisible()
  await expect(page.getByTestId('review-approve')).toHaveCount(0)
})

test('runs all guided checks against the preview and keeps the token out of the URL and storage', async ({ page }) => {
  const fixture = await mock(page, 'see', 'empty')
  await page.goto(root + '/see')
  await page.getByTestId('seeit-start').click()
  await page.getByRole('button', { name: 'Run all four checks' }).click()
  await expect(page.getByText('6 of 6 passed.')).toBeVisible()
  const engineWrites = fixture.writes.filter(write => write.path.startsWith('/previews/'))
  expect(engineWrites.map(write => write.path)).toEqual(['/previews/' + preview + '/leave-requests', '/previews/' + preview + '/leave-requests/7'])
  expect(engineWrites.every(write => write.access === 'preview-fixture-token')).toBe(true)
  expect(page.url()).not.toContain('preview-fixture-token')
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }))).not.toContain('preview-fixture-token')
})
