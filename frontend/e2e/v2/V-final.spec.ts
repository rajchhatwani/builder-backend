import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { members, projectId, root, user } from './fixtures/connect-a'
import { files, shipFixture } from './fixtures/ship'

test('Generate opens a bookmarkable file in Code without downloading a bundle', async ({ page }, info) => {
  const file = files[1].path
  const requests: string[] = []
  const responses: Record<string, unknown> = {
    '/account/refresh': { access_token: 'fixture' },
    '/account/me': user,
    [root]: { id: projectId, name: 'Warehouse', slug: 'warehouse', version: 3 },
    [root + '/members']: members,
    [root + '/status']: { ready: true, sections: [], counts: {}, issues: [] },
    [root + '/workspaces']: [],
  }
  const headers = {
    'access-control-allow-origin': 'http://localhost:5299',
    'access-control-allow-credentials': 'true',
    'access-control-allow-methods': 'GET, POST, OPTIONS',
    'access-control-allow-headers': 'authorization, content-type, last-event-id',
  }
  await page.addInitScript(() => localStorage.setItem('v2-language', 'en'))
  await page.route(url => url.port === '8000', async route => {
    if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers })
    const { pathname } = new URL(route.request().url())
    requests.push(pathname)
    const key = pathname.startsWith(root) ? pathname.slice(root.length) : pathname.replace('/generations/', '/generation/')
    const json = responses[pathname] ?? shipFixture[key]
    return route.fulfill({ headers, status: json ? 200 : 404, json: json ?? { code: 'not_found', details: [] } })
  })

  await page.goto(root + '/generate')
  await page.getByRole('button', { name: 'Preview files' }).click()
  await page.getByRole('link', { name: 'Open ' + file + ' in the editor' }).click()
  await expect(page).toHaveURL(url =>
    url.pathname === root + '/code' && url.searchParams.get('file') === file && url.searchParams.get('source') === 'manifest')
  if (info.project.name.startsWith('w360')) {
    await expect(page.getByRole('heading', { name: /Open this on a desktop/ })).toBeVisible()
  } else {
    await expect(page.getByRole('button', { name: 'Open self-host source' })).toBeVisible()
  }
  expect(requests).not.toContain(root + '/generate/download')
  const { violations } = await new AxeBuilder({ page }).analyze()
  expect(violations.map(({ id, nodes }) => ({ id, targets: nodes.map(node => node.target) }))).toEqual([])
})
