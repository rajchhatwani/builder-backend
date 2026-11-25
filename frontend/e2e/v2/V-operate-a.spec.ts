import { fileURLToPath } from 'node:url'
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { members, projectId, root, time, user } from './fixtures/connect-a'
import { advisor, hits, jobSettings, metric, metricValue, observation, operateSpec, report, reportRun, workflowSettings } from './fixtures/operate-a'

const titles = {
  observability: ['Observability', 'OpenTelemetry', 'OpenTelemetry is off'],
  jobs: ['Jobs and schedules', 'Job settings', 'Background jobs are switched off'],
  workers: ['Workers and queues', 'Queue coverage', 'Background jobs are switched off'],
  workflows: ['Workflows', 'Workflow runtime', 'Workflows are switched off'],
  traces: ['Traces', 'Trace waterfall', 'No trace loaded'],
  metrics: ['Metrics & reports', 'Total paid', 'No metrics yet'],
  search: ['Search', 'Search results', 'Add an entity first, then import records to search.'],
} as const
type Screen = keyof typeof titles
const states = ['normal', 'loading', 'empty', 'error'] as const
type State = typeof states[number]

test.use({ locale: 'en-US', timezoneId: 'UTC' })

test.beforeEach(async ({ page }) => {
  const font = (file: string) => fileURLToPath(new URL('./fixtures/ibm-plex/' + file, import.meta.url))
  await page.route(/^https:\/\/fonts\.googleapis\.com\/css2\?family=IBM\+Plex\+Sans/, route =>
    route.fulfill({ path: font('latin.css'), contentType: 'text/css' }))
  await page.route('https://fonts.gstatic.com/v2-test-typography/*.woff2', route =>
    route.fulfill({ path: font(new URL(route.request().url()).pathname.split('/').at(-1)!), contentType: 'font/woff2',
      headers: { 'access-control-allow-origin': '*' } }))
  await page.addInitScript(() => localStorage.setItem('v2-language', 'en'))
})

async function mock(page: Page, screen: Screen, state: State, role = 'owner') {
  const holdPaths: Partial<Record<Screen, string>> = {
    observability: '/observability', jobs: '/behavior/jobs', workflows: '/behavior/workflows', metrics: '/metrics',
    workers: '/spec', search: '/spec',
  }
  let release = () => {}
  const waiting = new Promise<void>(resolve => { release = resolve })
  let failing = state === 'error'
  let conflict = false
  let version = observation.version
  let settings = { ...observation }
  const requests: { method: string; path: string; body: unknown }[] = []
  await page.route(url => url.port === '8000', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const { pathname } = url
    const method = request.method()
    const headers = {
      'access-control-allow-origin': 'http://localhost:5299', 'access-control-allow-credentials': 'true',
      'access-control-allow-methods': 'GET, OPTIONS, PUT, POST, DELETE', 'access-control-allow-headers': 'content-type, authorization, x-requested-with, last-event-id',
    }
    const json = (data: unknown, status = 200) => route.fulfill({ json: data, status, headers })
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers })
    if (pathname === '/account/refresh') return json({ access_token: 'fixture' })
    if (pathname === '/account/me') return json(user)
    if (pathname === '/orgs') return json({ items: [], total: 0 })
    if (pathname === root) return json({ id: projectId, name: 'Billing workspace', slug: 'billing', version: 3 })
    if (pathname === root + '/status') return json({ ready: true, sections: [], counts: {}, issues: [] })
    if (pathname === root + '/members') return json(members.map(member => member.user_id === user.id ? { ...member, role } : member))
    if (pathname === root + '/workspaces' || pathname === root + '/previews') return json([])
    const path = pathname.slice(root.length)
    if (pathname.startsWith(root)) requests.push({ method, path: path + url.search, body: request.postData() ? request.postDataJSON() : null })
    if (method === 'GET' && path === holdPaths[screen]) {
      if (state === 'loading') await waiting
      if (failing) return json({ code: 'unavailable', message: 'Retry.', details: [] }, 503)
    }
    const empty = state === 'empty'
    if (path === '/spec') return json(empty && screen === 'workers' ? { ...operateSpec, jobs: null, workflows: null } :
      empty && screen === 'search' ? { entities: [] } : operateSpec)
    if (path === '/behavior/roles') return json({ roles: [{ name: 'employee', label: 'Employee' }] })
    if (path === '/behavior/issues' || path === '/observability/issues') return json({ issues: [] })
    if (path === '/observability') {
      if (method === 'PUT') {
        if (conflict) {
          conflict = false
          settings = { ...settings, service_name: 'other_editor', version: ++version }
          return json({ code: 'conflict', message: 'Reload the settings.', details: [] }, 409)
        }
        settings = { ...settings, ...request.postDataJSON(), version: ++version }
      }
      return json(empty ? { ...settings, enabled: false, version: 0, updated_at: null } : settings)
    }
    if (path === '/behavior/jobs') return json({ jobs: empty ? null : jobSettings, version: 3, updated_at: time })
    if (path === '/behavior/workflows') return json({ workflows: empty ? null : workflowSettings, version: 3, updated_at: time })
    if (path === '/advisor') return json(advisor)
    if (path === '/metrics') return json(empty ? { items: [], total: 0 } : { items: [metric], total: 1 })
    if (path === '/metrics/' + metric.key + '/value') return json(metricValue)
    if (path === '/reports') return json(empty ? { items: [], total: 0 } : { items: [report], total: 1 })
    if (path === '/reports/' + report.id + '/value') return json({ report_id: report.id, computed_at: time, values: reportRun.values })
    if (path === '/reports/' + report.id + '/runs') return json({ items: [reportRun], total: 1, offset: 0, limit: 20 })
    if (path === '/reports/' + report.id + '/run') return json(reportRun)
    if (path === '/search') return json(hits)
    if (path === '/search/reindex') return json({ project_id: projectId, index: 'database', indexed: 1,
      entities: [{ entity: 'Invoice', searchable_fields: 1, records: 1 }] })
    return json({ code: 'not_found', details: [] }, 404)
  })
  return { release, recover: () => { failing = false }, conflict: () => { conflict = true }, requests }
}

async function snapshot(page: Page) {
  await page.evaluate(() => document.fonts.ready)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBe(0)
  const result = await new AxeBuilder({ page }).analyze()
  expect(result.violations.map(item => ({ id: item.id, nodes: item.nodes.map(node => node.target) }))).toEqual([])
}

for (const [name, copy] of Object.entries(titles)) {
  const screen = name as Screen
  for (const state of states) {
    test(screen + ' ' + state, async ({ page }) => {
      const fixture = await mock(page, screen, state)
      const main = page.getByRole('main')
      const search = screen === 'search' && state === 'normal' ? '?q=paid&role=employee&entity=Invoice' : ''
      try {
        await page.goto(root + '/' + screen + search, { waitUntil: 'domcontentloaded' })
        await expect(main.getByRole('heading', { name: copy[0], exact: true, level: 1 })).toBeVisible()
        await expect(page.getByText('Ready', { exact: true }).first()).toBeVisible()
        if (screen === 'traces') {
          if (state === 'normal') await main.getByRole('button', { name: 'Load example' }).click()
          if (state === 'error') {
            await main.getByLabel('Trace document (JSON)').fill('{"trace_id":')
            await main.getByRole('button', { name: 'Show trace' }).click()
          }
          if (state === 'loading') {
            await page.evaluate(() => { File.prototype.text = () => new Promise<string>(() => {}) })
            await main.getByLabel('Or upload a .json file').setInputFiles({ name: 'trace.json', mimeType: 'application/json', buffer: Buffer.from('{}') })
          }
        }
        if (state === 'loading') await expect(main.getByRole('status', { name: 'Loading…' }).first()).toBeVisible()
        if (state === 'empty') await expect(main.getByRole('heading', { name: copy[2], exact: true })).toBeVisible()
        if (state === 'error') await expect(main.getByRole('alert').filter({ hasText: screen === 'traces'
          ? 'This trace could not be shown.' : 'We could not load this section.' })).toBeVisible()
        if (state === 'normal') {
          if (screen === 'metrics') await expect(main.getByText('600.6 USD', { exact: true })).toBeVisible()
          else await expect(main.getByRole('heading', { name: copy[1], exact: true })).toBeVisible()
        }
        await snapshot(page)
        if (screen === 'observability') {
          if (state === 'normal') await expect(page).toHaveScreenshot('observability-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('observability-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('observability-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('observability-error.png', { fullPage: true })
        }
        if (screen === 'jobs') {
          if (state === 'normal') await expect(page).toHaveScreenshot('jobs-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('jobs-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('jobs-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('jobs-error.png', { fullPage: true })
        }
        if (screen === 'workers') {
          if (state === 'normal') await expect(page).toHaveScreenshot('workers-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('workers-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('workers-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('workers-error.png', { fullPage: true })
        }
        if (screen === 'workflows') {
          if (state === 'normal') await expect(page).toHaveScreenshot('workflows-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('workflows-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('workflows-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('workflows-error.png', { fullPage: true })
        }
        if (screen === 'traces') {
          if (state === 'normal') await expect(page).toHaveScreenshot('traces-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('traces-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('traces-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('traces-error.png', { fullPage: true })
        }
        if (screen === 'metrics') {
          if (state === 'normal') await expect(page).toHaveScreenshot('metrics-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('metrics-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('metrics-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('metrics-error.png', { fullPage: true })
        }
        if (screen === 'search') {
          if (state === 'normal') await expect(page).toHaveScreenshot('search-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('search-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('search-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('search-error.png', { fullPage: true })
        }
        if (state === 'error' && screen !== 'traces') {
          fixture.recover()
          await main.getByRole('button', { name: 'Try again' }).first().click()
          await expect(main.getByRole('alert').filter({ hasText: 'We could not load this section.' })).toHaveCount(0)
        }
      } finally {
        fixture.release()
      }
    })
  }
}

test('observability conflict retains draft until reload', async ({ page }) => {
  const fixture = await mock(page, 'observability', 'normal')
  await page.goto(root + '/observability')
  const form = page.getByRole('main')
  const name = form.getByLabel('Service name')
  await name.fill('invoice_portal')
  fixture.conflict()
  await form.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(form.getByRole('button', { name: 'Reload', exact: true })).toBeVisible()
  await expect(name).toHaveValue('invoice_portal')
  expect(fixture.requests.find(item => item.method === 'PUT')?.body).toMatchObject({ service_name: 'invoice_portal', expected_version: 3 })
  await form.getByRole('button', { name: 'Reload', exact: true }).click()
  await expect(name).toHaveValue('other_editor')
  await name.fill('invoice_portal')
  await form.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(form.getByText('Saved (version 5).')).toBeVisible()
})

test('viewer can inspect report groups without report write controls', async ({ page }) => {
  await mock(page, 'metrics', 'normal', 'viewer')
  await page.goto(root + '/metrics?tab=reports')
  const main = page.getByRole('main')
  await main.getByRole('button', { name: 'Open', exact: true }).click()
  await expect(main.getByRole('heading', { name: 'Run history' })).toBeVisible()
  await expect(main.getByText('600.6 USD', { exact: true }).first()).toBeVisible()
  await expect(main.getByRole('button', { name: 'Run now' })).toHaveCount(0)
  await expect(main.getByRole('button', { name: 'New report' })).toHaveCount(0)
  await snapshot(page)
})
