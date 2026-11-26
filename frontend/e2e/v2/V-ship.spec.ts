import { fileURLToPath } from 'node:url'
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { members, projectId, root, user } from './fixtures/connect-a'
import { created, deployment, generationId, migration, paged, patch, proposal, proposalId, shipFixture, specHash } from './fixtures/ship'

const states = ['normal', 'loading', 'empty', 'error'] as const
type State = typeof states[number]
const labels = { deployment: 'Deploy', generate: 'Generate', upgrades: 'Upgrades' } as const
type Screen = keyof typeof labels
const headers = {
  'access-control-allow-origin': 'http://localhost:5299', 'access-control-allow-credentials': 'true',
  'access-control-allow-methods': 'GET, POST, PUT, OPTIONS',
  'access-control-allow-headers': 'content-type, authorization, x-requested-with, last-event-id',
  'access-control-expose-headers': 'Content-Disposition, X-Generation-Id, X-Spec-Hash',
}

test.use({ locale: 'en-US', timezoneId: 'UTC' })
test.beforeEach(async ({ page }) => {
  const font = (file: string) => fileURLToPath(new URL('./fixtures/ibm-plex/' + file, import.meta.url))
  await page.route(/^https:\/\/fonts\.googleapis\.com\/css2\?family=IBM\+Plex\+Sans/, route =>
    route.fulfill({ path: font('latin.css'), contentType: 'text/css' }))
  await page.route('https://fonts.gstatic.com/v2-test-typography/*.woff2', route =>
    route.fulfill({ path: font(new URL(route.request().url()).pathname.split('/').at(-1)!), contentType: 'font/woff2',
      headers: { 'access-control-allow-origin': '*' } }))
  await page.addInitScript(() => localStorage.setItem('v2-language', 'en'))
  await page.clock.setFixedTime(new Date(created))
})

async function mock(page: Page, screen: Screen, state: State = 'normal', options: { role?: string; conflicts?: boolean } = {}) {
  let release = () => {}
  const pending = new Promise<void>(resolve => { release = resolve })
  let settings = deployment
  let dismissed = false
  const calls: { path: string; method: string; query: URLSearchParams; body?: unknown }[] = []
  const core = { deployment: ['/deployment'], generate: ['/generations'], upgrades: ['/upgrades', '/scorecard'] }[screen]
  await page.route(url => url.port === '8000', async route => {
    const request = route.request()
    const { pathname, searchParams } = new URL(request.url())
    const method = request.method()
    const json = (data: unknown, status = 200) => route.fulfill({ json: data, status, headers })
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers })
    if (pathname === '/account/refresh') return json({ access_token: 'fixture' })
    if (pathname === '/account/me') return json(user)
    if (pathname === '/orgs') return json({ items: [], total: 0 })
    if (pathname === root) return json({ id: projectId, name: 'Warehouse', slug: 'warehouse', version: 3 })
    if (pathname === root + '/status') return json({ ready: true, sections: [], counts: {}, issues: [] })
    if (pathname === root + '/members') return json(members.map(member => member.user_id === user.id ? { ...member, role: options.role ?? 'owner' } : member))
    const path = pathname.startsWith(root) ? pathname.slice(root.length) : pathname.replace('/generations/', '/generation/')
    const body = request.postData() ? request.postDataJSON() : undefined
    calls.push({ path, method, query: searchParams, body })
    if (method === 'GET' && core.includes(path)) {
      if (state === 'loading') await pending
      if (state === 'error') return json({ code: 'unavailable', details: [] }, 503)
    }
    if (path === '/deployment') {
      if (method === 'PUT') {
        settings = { ...settings, ...body, version: settings.version + 1 }
        return json(settings)
      }
      return json(state === 'empty' ? { ...settings, version: 0, enabled: false, region: '', github_repo: '' } : settings)
    }
    if (path === '/generate/download') {
      if (options.conflicts && !searchParams.has('accept_unreadable_baseline')) {
        return json({ code: 'migration_baseline_unreadable', message: 'The previous generation cannot be read.', details: [{ generation_id: generationId }] }, 409)
      }
      if (options.conflicts && !searchParams.has('allow_destructive')) {
        return json({ code: 'destructive_migration', message: 'This change drops data.', details: [migration] }, 409)
      }
      return route.fulfill({ body: 'zip fixture', contentType: 'application/zip', headers: {
        ...headers, 'Content-Disposition': 'attachment; filename="warehouse.zip"', 'X-Generation-Id': generationId, 'X-Spec-Hash': specHash,
      } })
    }
    if (path === '/upgrades' && method === 'POST') return json(proposal, 201)
    if (path === '/upgrades/' + proposalId + '/patch') {
      return route.fulfill({ body: patch, contentType: 'text/x-diff', headers })
    }
    if (path === '/upgrades/' + proposalId + '/dismiss') {
      dismissed = true
      return json({ ...proposal, status: 'dismissed', decided_at: created })
    }
    if (dismissed && path === '/upgrades') return json(paged([{ ...proposal, status: 'dismissed', decided_at: created }]))
    if (dismissed && path === '/upgrades/' + proposalId) return json({ ...proposal, status: 'dismissed', decided_at: created })
    if (path === '/generations' && (state === 'empty' || searchParams.get('offset') === '20')) return json(paged([]))
    if (state === 'empty' && path === '/upgrades') return json(paged([]))
    if (Object.hasOwn(shipFixture, path)) return json(shipFixture[path])
    return json({ code: 'not_found', message: 'Not found.', details: [] }, 404)
  })
  return { release, calls }
}

const settled = {
  deployment: { normal: 'db.t4g.small', empty: 'Set up deployment', loading: 'Loading deployment settings…', error: 'Could not load the deployment settings.' },
  generate: { normal: specHash.slice(0, 12), empty: 'No downloads yet.', loading: 'Loading generation history…', error: 'Could not load generation history.' },
  upgrades: { normal: 'Score 77 / 100', empty: 'No upgrade proposals yet.', loading: 'Loading proposals…', error: 'Could not load the proposals' },
}

for (const name of Object.keys(labels) as Screen[]) {
  for (const state of states) {
    test(name + ' ' + state, async ({ page }) => {
      const fixture = await mock(page, name, state)
      try {
        await page.goto(root + '/' + name)
        const main = page.getByRole('main')
        await expect(main.getByRole('heading', { level: 1, name: labels[name] })).toBeVisible()
        const visible = settled[name][state]
        if (state === 'loading') await expect(main.getByRole('status', { name: visible })).toBeVisible()
        else await expect(main.getByText(visible, { exact: true })).toBeVisible()
        if (name === 'deployment' && state === 'normal') {
          await expect(main.getByText('No saved deployment problems.')).toBeVisible()
          await expect(main.getByRole('button', { name: 'Add an environment' })).toBeEnabled()
        }
        if (name === 'generate') await expect(main.getByRole('button', { name: 'Check', exact: true })).toBeEnabled()
        if (name === 'upgrades') {
          await expect(main.getByTestId('create-proposal')).toBeEnabled()
          if (state === 'normal') await expect(main.getByTestId('proposal')).toBeVisible()
          if (state === 'error') await expect(main.getByTestId('scorecard-error')).toBeVisible()
        }
        await page.evaluate(() => document.fonts.ready)
        expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBe(0)
        const audit = await new AxeBuilder({ page }).analyze()
        expect(audit.violations.map(violation => ({ id: violation.id, targets: violation.nodes.map(node => node.target) }))).toEqual([])
        if (state === 'normal') await expect(page).toHaveScreenshot(name + '-normal.png', { fullPage: true })
        if (state === 'loading') await expect(page).toHaveScreenshot(name + '-loading.png', { fullPage: true })
        if (state === 'empty') await expect(page).toHaveScreenshot(name + '-empty.png', { fullPage: true })
        if (state === 'error') await expect(page).toHaveScreenshot(name + '-error.png', { fullPage: true })
      } finally {
        fixture.release()
      }
    })
  }
}

test('Deploy retains a draft across tabs and saves with the loaded version', async ({ page }) => {
  const { calls } = await mock(page, 'deployment')
  await page.goto(root + '/deployment')
  await page.getByLabel('Region', { exact: true }).fill('ap-south-1')
  await page.getByRole('tab', { name: 'Settings form' }).click()
  await expect(page.getByLabel('Region', { exact: true })).toHaveValue('ap-south-1')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByText('Deployment settings saved. Saved (version 4).', { exact: true })).toBeVisible()
  expect(calls.find(call => call.path === '/deployment' && call.method === 'PUT')?.body).toMatchObject({
    expected_version: 3, region: 'ap-south-1',
  })
})

test('Generate confirms each migration refusal before the attachment is downloaded', async ({ page }) => {
  const { calls } = await mock(page, 'generate', 'normal', { conflicts: true })
  await page.goto(root + '/generate')
  await page.getByRole('button', { name: 'Download', exact: true }).click()
  await page.getByRole('button', { name: 'Review without a baseline' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Accept unreadable baseline' }).click()
  await expect(page.getByText('The field was removed.', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Review destructive download' }).click()
  const attachment = page.waitForEvent('download')
  await page.getByRole('dialog').getByRole('button', { name: 'Allow destructive download' }).click()
  expect((await attachment).suggestedFilename()).toBe('warehouse.zip')
  expect(calls.filter(call => call.path === '/generate/download').map(call => Object.fromEntries(call.query))).toEqual([
    {}, { accept_unreadable_baseline: 'true' }, { accept_unreadable_baseline: 'true', allow_destructive: 'true' },
  ])
})

test('Generate links preview files to the editor and exposes history detail', async ({ page }) => {
  await mock(page, 'generate')
  await page.goto(root + '/generate')
  await page.getByRole('button', { name: 'Preview files', exact: true }).click()
  const file = page.getByRole('link', { name: 'Open app/main.py in the editor', exact: true })
  await expect(file).toHaveAttribute('href', /\/code\?.*file=app%2Fmain.py/)
  await page.getByRole('button', { name: /view generation/ }).click()
  await expect(page.getByRole('heading', { name: 'Download details' })).toBeVisible()
  await expect(page.getByRole('table', { name: 'File manifest' })).toBeVisible()
  await expect(page).toHaveURL(new RegExp('generation=' + generationId))
})

test('Upgrades downloads the named patch and retains a dismissed proposal', async ({ page }) => {
  await mock(page, 'upgrades')
  await page.goto(root + '/upgrades')
  await page.getByTestId('fix-open-upgrade').click()
  await expect(page.getByTestId('patch')).toBeVisible()
  const attachment = page.waitForEvent('download')
  await page.getByTestId('download-patch').click()
  expect((await attachment).suggestedFilename()).toBe('upgrade-' + proposalId + '.patch')
  await page.getByTestId('dismiss').click()
  await page.getByTestId('confirm-decide').click()
  await expect(page.getByTestId('proposal-status')).toHaveText('Dismissed')
  await expect(page.getByTestId('closed-note')).toContainText('Dismissed')
})
