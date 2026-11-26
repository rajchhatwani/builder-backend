import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const project = '95ff34eb-4d07-4a60-8669-aaf1cf5442ca'
const workspace = '700e83e8-4073-42a4-a8a4-54458f7bb71d'
const root = '/projects/' + project
const filesPath = root + '/workspaces/' + workspace + '/files'
const path = 'app/hooks.py'
const entry = { path, editable: true, zone: 'custom', size: 105 }
const files = [entry, { path: 'app/main.py', editable: false, zone: 'generated', size: 30 }]
const contents: Record<string, string> = {
  [path]: 'from app.models import LeaveRequest\n\nasync def notify_manager(request: LeaveRequest):\n    return request.id\n',
  'app/main.py': 'from fastapi import FastAPI\n\napp = FastAPI()\n',
}
type State = 'normal' | 'loading' | 'empty' | 'error'
const screenshots: Record<State, (page: Page) => Promise<void>> = {
  normal: page => expect(page).toHaveScreenshot('code-normal.png', { fullPage: true }),
  loading: page => expect(page).toHaveScreenshot('code-loading.png', { fullPage: true }),
  empty: page => expect(page).toHaveScreenshot('code-empty.png', { fullPage: true }),
  error: page => expect(page).toHaveScreenshot('code-error.png', { fullPage: true }),
}

async function mock(page: Page, state: State, role = 'owner') {
  await page.addInitScript(() => localStorage.setItem('v2-language', 'en'))
  const headers = {
    'access-control-allow-origin': 'http://localhost:5299',
    'access-control-allow-credentials': 'true',
    'access-control-allow-methods': 'GET, POST, PUT, OPTIONS',
    'access-control-allow-headers': 'content-type, authorization, x-requested-with',
  }
  let release = () => {}
  const delay = new Promise<void>(resolve => { release = resolve })
  const requests: string[] = []
  let firstList = true
  await page.route(url => url.port === '8000', async route => {
    const request = route.request()
    const address = new URL(request.url())
    const path = address.pathname
    if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers })
    const send = (json: unknown, status = 200) => route.fulfill({ status, headers, json })
    requests.push(path)
    if (path === root + '/status') return send({ sections: [] })
    if (path === '/account/refresh') return send({ access_token: 'fixture' })
    if (path === '/account/me') return send({ id: 'viewer', platform_role: 'customer' })
    if (path === root + '/members') return send([{ user_id: 'viewer', role }])
    if (path === root + '/workspaces') return send([{ id: workspace, name: 'Leave requests', state: 'active' }])
    if (path === filesPath) {
      if (firstList) {
        firstList = false
        if (state === 'loading') await delay
        if (state === 'error') return send({ code: 'fixture_failure', message: 'File list unavailable', details: [] }, 500)
      }
      return send(state === 'empty' ? [] : files)
    }
    if (path === filesPath + '/content') {
      const file = files.find(file => file.path === address.searchParams.get('path'))
      if (file) return send({ ...file, content: contents[file.path], sha256: 'a'.repeat(64) })
    }
    if (path === root + '/generate/preview' && request.method() === 'POST') return send({
      spec_hash: 'fixture', total_files: 1, total_size: 30, files: [{ path: 'app/main.py', size: 30 }],
    })
    return send({ code: 'fixture_missing', message: 'No such fixture', details: [] }, 404)
  })
  return { release, requests }
}

function editorUrl() {
  return root + '/code?' + new URLSearchParams({ workspace, file: path })
}

for (const state of ['normal', 'loading', 'empty', 'error'] as const) {
  test('code ' + state, async ({ page }, info) => {
    const fixture = await mock(page, state)
    try {
      await page.goto(editorUrl())
      if (info.project.name.startsWith('w360')) {
        await expect(page.getByRole('heading', { name: /Open this on a desktop/ })).toBeVisible()
        expect(fixture.requests).not.toContain(filesPath)
      } else {
        if (state === 'normal') {
          await expect(page.getByRole('tab', { name: 'Problems (0)' })).toBeVisible()
          await expect(page.getByRole('textbox', { name: 'Editor for ' + path })).toBeVisible()
          await expect(page.getByText('Editable', { exact: true })).toBeVisible()
        }
        if (state === 'loading') await expect(page.getByRole('status', { name: 'Loading files…' })).toBeVisible()
        if (state === 'empty') await expect(page.getByRole('heading', { name: 'This source has no files yet.' })).toBeVisible()
        if (state === 'error') await expect(page.getByRole('alert')).toHaveText(/Could not load the files/)
      }
      await page.evaluate(() => document.fonts.ready.then(() => undefined))
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(await page.evaluate(() => window.innerWidth))
      const result = await new AxeBuilder({ page }).analyze()
      expect(result.violations.map(({ id, nodes }) => ({ id, targets: nodes.map(node => node.target) }))).toEqual([])
      await screenshots[state](page)
    } finally { fixture.release() }
  })
}

test('opens the named file for a viewer and finds its content from another tab', async ({ page }, info) => {
  test.skip(info.project.name.startsWith('w360'), 'The phone renders DesktopOnlyCard.')
  await mock(page, 'normal', 'viewer')
  await page.goto(editorUrl())
  await expect(page.getByRole('textbox', { name: 'Editor for ' + path })).toBeVisible()
  await expect(page.getByText('Read-only', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save' })).toHaveCount(0)
  await page.getByRole('navigation', { name: 'Files' }).getByRole('button', { name: /main.py/ }).click()
  await expect(page.getByRole('textbox', { name: 'Editor for app/main.py' })).toBeVisible()
  await page.getByRole('button', { name: 'Search across files' }).click()
  await page.getByRole('searchbox').fill('notify_manager')
  await page.getByRole('button', { name: /app\/hooks.py · line 3/ }).click()
  await expect(page.getByRole('textbox', { name: 'Editor for ' + path })).toBeVisible()
  expect(new URL(page.url()).searchParams.get('line')).toBe('3')
})

test('Generate Preview files navigates to the editor manifest', async ({ page }, info) => {
  test.skip(info.project.name.startsWith('w360'), 'The phone renders DesktopOnlyCard.')
  const fixture = await mock(page, 'normal')
  await page.goto(root + '/generate')
  await page.getByRole('button', { name: 'Preview files' }).click()
  await page.getByRole('link', { name: 'Open app/main.py in the editor' }).click()
  await expect(page.getByText('30 bytes', { exact: true })).toBeVisible()
  expect(new URL(page.url()).pathname).toBe(root + '/code')
  expect(fixture.requests).not.toContain(root + '/generate/download')
})
