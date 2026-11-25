import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const projectId = '95ff34eb-4d07-4a60-8669-aaf1cf5442ca'
const statusPath = `/projects/${projectId}/status`
const homePath = `/projects/${projectId}/overview`
const signInStep = { id: 'consider_auth', title: 'Decide how people sign in', reason: 'Your API has no user accounts yet.', section: 'auth', dismissed: false }
const generate = { id: 'generate', title: 'Generate your backend', reason: 'The model is valid and nothing is left to fix.', section: 'generate', dismissed: false }
const emptyStep = { id: 'add_entity', title: 'Add your first entity', reason: 'A backend needs at least one thing to store.', section: 'model', dismissed: false }
const sections = [
  ['model', 'Data model'], ['auth', 'Sign-in'], ['authorization', 'Roles and access'], ['payments', 'Payments'],
  ['storage', 'File storage'], ['observability', 'Observability'], ['deployment', 'Deployment'], ['documents', 'Documents'],
  ['state_machines', 'State machines'], ['settings', 'Settings, sequences and lists'], ['history', 'Change history'], ['hooks', 'Custom hooks'], ['seed', 'Seed data'],
] as const

type State = 'normal' | 'loading' | 'empty' | 'error'
type Screen = 'kit' | 'status'
const states: State[] = ['normal', 'loading', 'empty', 'error']
const screenshots: Record<State, (page: Page, screen: Screen) => Promise<void>> = {
  normal: (page, screen) => expect(page).toHaveScreenshot(`${screen}-normal.png`, { fullPage: true }),
  loading: (page, screen) => expect(page).toHaveScreenshot(`${screen}-loading.png`, { fullPage: true }),
  empty: (page, screen) => expect(page).toHaveScreenshot(`${screen}-empty.png`, { fullPage: true }),
  error: (page, screen) => expect(page).toHaveScreenshot(`${screen}-error.png`, { fullPage: true }),
}

async function mockStatus(page: Page, state: State, writeError?: number) {
  let dismissed = false
  let retried = false
  let release = () => {}
  const loading = new Promise<void>(resolve => { release = resolve })
  const fixture = () => ({
    ready: state !== 'empty',
    issues: [],
    counts: { entities: state === 'empty' ? 0 : 2, relations: 0, state_machines: 0, settings: 0, sequences: 0, lists: 0, history_configs: 0, hooks: 0, seed_profiles: 0 },
    sections: sections.map(([id, label]) => ({ id, label, configured: state !== 'empty' && (id === 'model' || id === 'storage'), issue_count: 0 })),
    next_step: state === 'empty' ? emptyStep : dismissed ? generate : signInStep,
    dismissed_steps: dismissed ? [{ ...signInStep, dismissed: true }] : [],
  })
  await page.route(url => url.port === '8000' && ['/account/refresh', '/account/me'].includes(url.pathname), async route => {
    const headers = {
      'access-control-allow-origin': 'http://localhost:5299',
      'access-control-allow-credentials': 'true',
      'access-control-allow-methods': 'GET, POST, OPTIONS',
      'access-control-allow-headers': 'content-type, authorization, x-requested-with',
    }
    if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers })
    return route.fulfill({ status: 200, headers, json: { access_token: 'fixture', id: 'fixture-user' } })
  })
  await page.route(url => url.pathname.startsWith(statusPath), async route => {
    const headers = { 'access-control-allow-origin': 'http://localhost:5299', 'access-control-allow-credentials': 'true', 'access-control-allow-methods': 'GET, POST, DELETE, OPTIONS', 'access-control-allow-headers': 'content-type, authorization' }
    const method = route.request().method()
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers })
    if (method !== 'GET') {
      if (writeError) return route.fulfill({ status: writeError, headers, json: { code: 'fixture', message: 'Fixture request failed.', details: [] } })
      dismissed = method === 'POST'
    } else if (state === 'error' && !retried) {
      retried = true
      return route.fulfill({ status: 500, headers, json: { code: 'fixture', message: 'Fixture request failed.', details: [] } })
    } else if (state === 'loading') await loading
    return route.fulfill({ status: 200, headers, json: fixture() })
  })
  return release
}

async function checkPage(page: Page, screen: Screen, state: State) {
  await page.evaluate(() => document.fonts.ready.then(() => undefined))
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(await page.evaluate(() => window.innerWidth))
  const results = await new AxeBuilder({ page }).analyze()
  expect(results.violations.map(({ id, nodes }) => ({ id, targets: nodes.map(node => node.target) }))).toEqual([])
  await screenshots[state](page, screen)
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('v2-language', 'en')
  })
})

for (const state of states) {
  test(`kit ${state}`, async ({ page }) => {
    await page.goto(state === 'normal' ? '/v2-kit' : `/v2-kit?state=${state}`)
    await expect(page.getByRole('heading', { name: 'Component kit' })).toBeVisible()
    await expect(state === 'normal' ? page.getByRole('heading', { name: 'Form controls' })
      : state === 'loading' ? page.getByRole('status', { name: 'Loading…' })
      : state === 'empty' ? page.getByRole('heading', { name: 'No examples match.' })
      : page.getByRole('alert')).toBeVisible()
    await checkPage(page, 'kit', state)
  })

  test(`status ${state}`, async ({ page }) => {
    const release = await mockStatus(page, state)
    try {
      await page.goto(homePath)
      await expect(page.getByRole('heading', { name: 'Home', exact: true })).toBeVisible()
      await expect(state === 'normal' ? page.getByText('Ready to generate.', { exact: true })
        : state === 'loading' ? page.getByRole('status', { name: 'Loading project status…' })
        : state === 'empty' ? page.getByRole('heading', { name: 'Add your first entity' }).last()
        : page.getByRole('alert')).toBeVisible()
      await checkPage(page, 'status', state)
      if (state === 'error') {
        await page.getByRole('button', { name: 'Try again' }).click()
        await expect(page.getByText('Ready to generate.', { exact: true })).toBeVisible()
      }
    } finally {
      release()
    }
  })
}

test('dismisses and restores the optional step', async ({ page }) => {
  await mockStatus(page, 'normal')
  await page.goto(homePath)
  await page.getByRole('button', { name: 'Not now' }).click()
  await expect(page.getByRole('heading', { name: 'Dismissed steps' })).toBeVisible()
  await page.getByRole('button', { name: 'Show again' }).click()
  await expect(page.getByRole('button', { name: 'Not now' })).toBeVisible()
})

test('honors a viewer write denial', async ({ page }) => {
  await mockStatus(page, 'normal', 403)
  await page.goto(homePath)
  await page.getByRole('button', { name: 'Not now' }).click()
  await expect(page.getByText('Only project editors and owners can dismiss or restore steps.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Not now' })).toHaveCount(0)
})

test('returns focus to the dialog trigger on Escape', async ({ page }) => {
  await page.goto('/v2-kit')
  const trigger = page.getByRole('button', { name: 'Dialog', exact: true })
  await trigger.click()
  await expect(page.getByRole('dialog', { name: 'Dialog' })).toBeVisible()
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
  await page.keyboard.press('Escape')
  await expect(trigger).toBeFocused()
})

test('offers a status refresh after a write conflict', async ({ page }) => {
  await mockStatus(page, 'normal', 409)
  await page.goto(homePath)
  await page.getByRole('button', { name: 'Not now' }).click()
  await expect(page.getByText('Someone else changed this section', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: 'Reload' }).click()
  await expect(page.getByText('Someone else changed this section', { exact: false })).toHaveCount(0)
})
