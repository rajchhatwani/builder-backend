import { fileURLToPath } from 'node:url'
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { members, model, payments, projectId, root, sizing, storage, token, user } from './fixtures/connect-a'

test.use({ locale: 'en-US', timezoneId: 'UTC' })

const states = ['normal', 'loading', 'empty', 'error'] as const
type State = typeof states[number]
type Section = 'payments' | 'storage' | 'integrations'

async function mock(page: Page, section: Section, state: State, role = 'owner') {
  let release = () => {}
  const waiting = new Promise<void>(resolve => { release = resolve })
  let failed = state === 'error'
  let ready = state !== 'empty'
  let enabled = true
  let membersData = members.map(member => member.user_id === user.id ? { ...member, role } : member)
  let tokens = ready ? [token] : []
  let config = section === 'payments' ? payments : storage
  const target = section === 'integrations' ? '/members' : '/' + section
  const writes: { method: string; path: string; body: unknown }[] = []
  await page.route(url => url.port === '8000', async route => {
    const url = new URL(route.request().url())
    const path = url.pathname
    const method = route.request().method()
    const headers = {
      'access-control-allow-origin': 'http://localhost:5299',
      'access-control-allow-credentials': 'true', 'access-control-allow-methods': 'GET, POST, OPTIONS, PUT, PATCH, DELETE',
      'access-control-allow-headers': 'content-type, authorization, x-requested-with, last-event-id',
    }
    const json = (data: unknown, status = 200) => route.fulfill({ json: data, status, headers })
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers })
    if (path === '/account/refresh') return json({ access_token: 'fixture' })
    if (path === '/account/me') return json(user)
    if (path === '/orgs') return json({ items: [{ id: 'org', slug: 'people', name: 'People', kind: 'team' }], total: 1 })
    if (path === '/orgs/people/plan') return json({
      plan: { allow_mcp: true, display_name: 'Team' }, usage: { mcp_tokens_used: 1, mcp_tokens_cap: 3 },
    })
    if (path === root) return json({ id: projectId, name: 'People Directory', slug: 'directory', organization_id: 'org', version: 1 })
    if (path === root + '/status') return json({ ready: true, sections: [], counts: {}, issues: [] })
    if (path === root + '/spec') return json(model)
    if (path === root + target && method === 'GET') {
      if (state === 'loading') await waiting
      if (failed) return json({ code: 'unavailable', message: 'Retry.', details: [] }, 503)
    }
    if (path === root + '/members') return json(ready || section !== 'integrations' ? membersData : [])
    if (path === root + '/tokens') return json(tokens)
    if (path === root + '/payments/sizing') return json({ sizing, issues: [] })
    if (path === root + target && method === 'GET') {
      return ready ? json({ ...config, enabled }) : json({ code: 'not_found', message: section + ' settings not found', details: [] }, 404)
    }
    if (path === root + target + '/impact') {
      return json({ enabled, action: url.searchParams.get('action'), can_proceed: true, warnings: ['The next build changes.'], blockers: [] })
    }
    if (['PUT', 'POST', 'PATCH', 'DELETE'].includes(method)) {
      const body = route.request().postData() ? route.request().postDataJSON() : null
      writes.push({ method, path, body })
      if (method === 'PUT' && path === root + target) {
        config = { ...config, ...body }
        ready = true
        return json({ ...config, enabled })
      }
      if (path === root + target + '/disable') {
        enabled = false
        return json({ ...config, enabled })
      }
      if (path === root + '/members/alex/mcp') {
        membersData = membersData.map(member => member.user_id === 'alex' ? { ...member, mcp_enabled: body.mcp_enabled } : member)
        return json(membersData[1])
      }
      if (path === root + '/tokens/' + token.id) {
        tokens = []
        return route.fulfill({ status: 204, headers })
      }
    }
    return json({ code: 'not_found', details: [] }, 404)
  })
  return { release, recover: () => { failed = false }, writes }
}

test.beforeEach(async ({ page }) => {
  const font = (file: string) => fileURLToPath(new URL('./fixtures/ibm-plex/' + file, import.meta.url))
  await page.route(/^https:\/\/fonts\.googleapis\.com\/css2\?family=IBM\+Plex\+Sans/, route =>
    route.fulfill({ path: font('latin.css'), contentType: 'text/css' }))
  await page.route('https://fonts.gstatic.com/v2-test-typography/*.woff2', route =>
    route.fulfill({ path: font(new URL(route.request().url()).pathname.split('/').at(-1)!), contentType: 'font/woff2',
      headers: { 'access-control-allow-origin': '*' } }))
  await page.addInitScript(() => localStorage.setItem('v2-language', 'en'))
})

const copy = {
  payments: { title: 'Payments', normal: 'What this means for your servers', empty: 'Fill in the settings below, then turn payments on.',
    error: 'Could not load the payments settings.' },
  storage: { title: 'File uploads', normal: 'Upload pipeline', empty: 'Fill in the settings below, then turn file uploads on.',
    error: 'Could not load the file upload settings.' },
  integrations: { title: 'Integrations', normal: 'Project assistant', empty: 'No members yet.', error: "Can't load the members." },
} as const

for (const section of ['payments', 'storage', 'integrations'] as const) {
  for (const state of states) {
    test(section + ' ' + state, async ({ page }) => {
      const fixture = await mock(page, section, state)
      try {
        await page.goto(root + '/' + section + (section === 'integrations' ? '' : '?tab=guided'), { waitUntil: 'domcontentloaded' })
        const main = page.getByRole('main')
        await expect(main.getByRole('heading', { name: copy[section].title, exact: true })).toBeVisible()
        await expect(page.locator('[aria-current="page"]').filter({ hasText: 'People Directory' })).toBeVisible()
        await expect(page.getByText('Ready', { exact: true })).toBeVisible()
        if (state === 'loading') await expect(main.getByRole('status', { name: 'Loading…' }).first()).toBeVisible()
        else await expect(main.getByText(copy[section][state], { exact: true }).first()).toBeVisible()
        if (section === 'payments' && state === 'normal') await expect(main.getByText('Connection budget', { exact: true })).toBeVisible()
        if (section === 'integrations') await expect(main.getByText('Team includes MCP')).toBeVisible()
        await page.evaluate(() => document.fonts.ready)
        expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBe(0)
        const audit = await new AxeBuilder({ page }).analyze()
        expect(audit.violations.map(item => ({ id: item.id, targets: item.nodes.map(node => node.target) }))).toEqual([])
        if (section === 'payments') {
          if (state === 'normal') await expect(page).toHaveScreenshot('payments-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('payments-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('payments-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('payments-error.png', { fullPage: true })
        }
        if (section === 'storage') {
          if (state === 'normal') await expect(page).toHaveScreenshot('storage-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('storage-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('storage-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('storage-error.png', { fullPage: true })
        }
        if (section === 'integrations') {
          if (state === 'normal') await expect(page).toHaveScreenshot('integrations-normal.png', { fullPage: true })
          if (state === 'loading') await expect(page).toHaveScreenshot('integrations-loading.png', { fullPage: true })
          if (state === 'empty') await expect(page).toHaveScreenshot('integrations-empty.png', { fullPage: true })
          if (state === 'error') await expect(page).toHaveScreenshot('integrations-error.png', { fullPage: true })
        }
        if (state === 'error') {
          fixture.recover()
          await main.getByRole('button', { name: 'Try again' }).click()
          await expect(main.getByText(section === 'integrations' ? 'Alex Bench' : copy[section].normal, { exact: true })).toBeVisible()
        }
      } finally {
        fixture.release()
      }
    })
  }
}

test('payments preserves a draft between tabs and previews a destructive switch', async ({ page }) => {
  const fixture = await mock(page, 'payments', 'normal')
  await page.goto(root + '/payments?tab=form')
  const amount = page.getByRole('textbox', { name: 'Largest single payment in the smallest unit' })
  await amount.fill('120000')
  await page.getByRole('tab', { name: 'Guided setup' }).click()
  await expect(amount).toHaveValue('120000')
  await page.getByRole('button', { name: 'Save payments settings' }).click()
  await expect(page.getByText('Payments settings saved.', { exact: true })).toBeVisible()
  expect(fixture.writes[0]).toMatchObject({ method: 'PUT', path: root + '/payments', body: { max_amount_minor: 120000 } })
  await page.getByRole('button', { name: 'Turn off…' }).click()
  const dialog = page.getByRole('dialog', { name: 'Turn off payments' })
  await expect(dialog.getByText('The next build changes.')).toBeVisible()
  await dialog.getByRole('button', { name: 'Turn off payments' }).click()
  await expect(dialog).toBeHidden()
  expect(fixture.writes[1]).toEqual({ method: 'POST', path: root + '/payments/disable', body: { confirm: true } })
})

test('file uploads links to the generated IAM policy with the file selected', async ({ page }) => {
  await mock(page, 'storage', 'normal')
  await page.goto(root + '/storage?tab=guided')
  const link = page.getByRole('link', { name: 'Open IAM policy in the editor' })
  await expect(link).toBeVisible()
  const destination = new URL((await link.getAttribute('href'))!, page.url())
  expect(destination.pathname).toBe(root + '/code')
  expect(destination.searchParams.get('file')).toBe('deploy/storage/iam-policy.json')
})

test('integrations confirms disabling member access and revoking tokens', async ({ page }) => {
  const fixture = await mock(page, 'integrations', 'normal')
  await page.goto(root + '/integrations')
  const alex = page.getByRole('row').filter({ hasText: 'Alex Bench' })
  await alex.getByRole('button', { name: 'Enable' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Allow MCP access' }).click()
  await expect(alex.getByRole('button', { name: 'Disable' })).toBeVisible()
  await alex.getByRole('button', { name: 'Disable' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Revoke MCP access' }).click()
  await expect(alex.getByRole('button', { name: 'Enable' })).toBeVisible()
  await page.getByRole('button', { name: 'Revoke', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Revoke token' }).click()
  await expect(page.getByText('No tokens are pinned to this project.')).toBeVisible()
  expect(fixture.writes).toEqual([
    { method: 'PATCH', path: root + '/members/alex/mcp', body: { mcp_enabled: true } },
    { method: 'PATCH', path: root + '/members/alex/mcp', body: { mcp_enabled: false } },
    { method: 'DELETE', path: root + '/tokens/' + token.id, body: null },
  ])
})

test('project viewers can review MCP membership', async ({ page }) => {
  const requested: string[] = []
  page.on('request', request => { if (request.url().endsWith('/tokens')) requested.push(request.url()) })
  await mock(page, 'integrations', 'normal', 'viewer')
  await page.goto(root + '/integrations')
  await expect(page.getByText('Only project owners can manage MCP access and pinned tokens.')).toBeVisible()
  await expect(page.getByText('Alex Bench')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Enable', exact: true })).toHaveCount(0)
  expect(requested).toEqual([])
})

for (const section of ['payments', 'storage'] as const) {
  test(section + ' viewer can review settings without seeing write controls', async ({ page }) => {
    await mock(page, section, 'normal', 'viewer')
    await page.goto(root + '/' + section + '?tab=guided')
    await expect(page.getByText('You can look at this but not change it. Your role is viewer.')).toBeVisible()
    await expect(page.getByRole('textbox', { name: section === 'storage' ? 'Bucket name' : 'Largest single payment in the smallest unit' })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Turn off…' })).toHaveCount(0)
  })
}
