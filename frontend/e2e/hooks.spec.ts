/** F1-5: Build > Hooks (new shell only). Refresh baselines with
 *  `npx playwright test e2e/hooks.spec.ts --update-snapshots`. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { createProjectViaApi, signedInUser, watchProblems, type Api } from './helpers'

const WEB = process.env.E2E_WEB_PORT ?? '5199'
test.use({
  storageState: { cookies: [], origins: [{ origin: `http://localhost:${WEB}`, localStorage: [{ name: 'ui.shell', value: 'v2' }] }] },
})
const FIXTURES = fileURLToPath(new URL('../../tests/fixtures/specs/', import.meta.url))

async function importFixture(api: Api, projectId: string, file: string) {
  const spec = JSON.parse(readFileSync(FIXTURES + file, 'utf8'))
  const r = await api.put(`/projects/${projectId}/spec`, spec)
  expect(r.status(), await r.text()).toBe(200)
}
const hook = (page: Page, name: string) => page.getByTestId('hook-row').filter({ has: page.locator(`legend:text-is("${name}")`) })
const mask = (page: Page) => [page.locator('nav[data-shell="v2"] .muted, nav[data-shell="v2"] [data-testid=shell-project]')]
async function axeClean(page: Page, name: string) {
  const axe = await new AxeBuilder({ page }).analyze()
  expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), `axe on ${name}`).toEqual([])
}
const save = (page: Page) => page.getByRole('button', { name: 'Save', exact: true }).click()

test('hooks: declared hooks are listed; declare one, save, reload, see it and its stub', async ({ page, request }, info) => {
  test.setTimeout(90_000)
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Invoice Desk')
  await importFixture(api, id, 'hooks_invoice.json')
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/overview`)
  if (info.project.name === 'desktop') await page.locator('aside[data-sidebar]').getByRole('link', { name: 'Hooks', exact: true }).click()
  else await page.goto(`/#/p/${id}/hooks`)
  await expect(page).toHaveURL(new RegExp(`#/p/${id}/hooks$`))
  await expect(page.getByRole('heading', { level: 1, name: 'Hooks' })).toBeVisible()
  await expect(page.getByTestId('hook-row')).toHaveCount(2)
  const match = hook(page, 'match_invoice')
  await expect(match.getByTestId('hook-summary')).toContainText('Invoice.transition_guard(submit)')
  await expect(match.getByTestId('hook-summary')).toContainText('fail_closed')
  await expect(match.getByTestId('stub-path')).toHaveText('app/custom/hooks/match_invoice.py')
  await expect(match.getByTestId('stub-signature')).toHaveText('def match_invoice(data: MatchInput) -> MatchResult:  # platform:signature (fixed)')
  await expect(match.getByTestId('gate-command')).toHaveText('python -m app.platform_gate')
  await expect(match.getByText('Run the gate in your generated project')).toBeVisible()

  // declare a validate hook: the point picker only offers real points; kind/policy are restricted
  await page.getByRole('button', { name: 'Declare a hook' }).click()
  const fresh = page.getByTestId('hook-row').last() // its legend changes as the name is typed
  await fresh.getByLabel('Hook name').fill('check_amounts')
  await expect(fresh.getByTestId('stub-path')).toHaveText('app/custom/hooks/check_amounts.py')
  await fresh.getByLabel('Where it runs').selectOption('Invoice.validate')
  await expect(fresh.getByLabel('Kind').locator('option')).toHaveText(['pure'])
  await expect(fresh.getByLabel('If the hook fails').locator('option')).toHaveText(['fail_closed'])
  await expect(fresh.getByLabel('Where it runs').locator('option[value="Invoice.transition_guard(auto_approve)"]')).toHaveCount(0)
  await expect(fresh.getByLabel('Where it runs').locator('option[value="Invoice.transition_guard(approve)"]')).toHaveCount(1)
  await fresh.getByLabel('amount decimal', { exact: true }).check()
  await fresh.getByLabel('po_amount decimal', { exact: true }).check()
  await expect(fresh.getByTestId('hook-form')).toContainText('valid: bool, message: string?')
  await save(page)
  await expect(page.getByTestId('save-note')).toContainText('Saved')
  await expect(page.getByTestId('issue-summary')).toHaveCount(0)

  await page.reload()
  await expect(page.getByTestId('hook-row')).toHaveCount(3)
  const saved = hook(page, 'check_amounts')
  await expect(saved.getByTestId('hook-summary')).toContainText('Invoice.validate')
  await expect(saved.getByTestId('hook-summary')).toContainText('amount: decimal, po_amount: decimal')
  await expect(saved.getByTestId('hook-summary')).toContainText('valid: bool, message: string?')
  await expect(saved.getByTestId('stub-signature')).toHaveText('def check_amounts(data: CheckAmountsInput) -> CheckAmountsResult:  # platform:signature (fixed)')
  await saved.getByText('Preview the whole stub').click()
  await expect(saved.getByTestId('stub-text')).toContainText('# <agent:body hook=check_amounts>')

  const [download] = await Promise.all([page.waitForEvent('download'), saved.getByRole('button', { name: 'Download stub' }).click()])
  expect(download.suggestedFilename()).toBe('check_amounts.py')
  const text = readFileSync((await download.path())!, 'utf8')
  expect(text).toContain('# platform:hook check_amounts  point=Invoice.validate  kind=pure  contract=v1')
  expect(text).toContain('from app.hooks_gen.contracts import CheckAmountsInput, CheckAmountsResult')
  expect(text).toContain('    # <agent:body hook=check_amounts>\n    raise NotImplementedError\n    # </agent:body>\n')

  await page.getByRole('heading', { level: 1, name: 'Hooks' }).scrollIntoViewIfNeeded()
  await page.waitForTimeout(300)
  await expect.soft(page).toHaveScreenshot('hooks-list.png', { mask: mask(page) })
  await axeClean(page, `${info.project.name} list`)
  watch.assertNone()
})

test('hooks: the backend message shows next to the field; a stale save is a conflict; remove', async ({ page, request }, info) => {
  test.setTimeout(90_000)
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Invoice Desk 2')
  await importFixture(api, id, 'hooks_invoice.json')
  await page.goto(`/#/p/${id}/hooks`)

  // the UI keeps kind/policy legal, but a budget over the ceiling is the backend's call
  const match = hook(page, 'match_invoice')
  await match.getByRole('button', { name: 'Edit', exact: true }).click()
  await match.getByLabel('CPU budget (ms)').fill('5000')
  await save(page)
  await expect(page.getByTestId('issue-summary')).toContainText('1 problem')
  await expect(match.getByTestId('field-error')).toHaveText('cpu_ms must be 1 to 1000 for a pure hook')
  await expect(match.getByLabel('CPU budget (ms)')).toHaveAttribute('aria-invalid', 'true')
  await expect(match.getByTestId('hook-issues')).toContainText('cpu_ms must be 1 to 1000 for a pure hook')
  await page.getByRole('heading', { level: 1, name: 'Hooks' }).scrollIntoViewIfNeeded()
  await page.waitForTimeout(300)
  await expect.soft(page).toHaveScreenshot('hooks-issue.png', { mask: mask(page) })
  await axeClean(page, `${info.project.name} with issues`)

  // an illegal combination written behind the page's back (after_commit cannot be fail_closed) is explained on load
  const cur = await (await api.get(`/projects/${id}/behavior/hooks`)).json()
  const hooks = cur.hooks.map((h: { name: string }) => (h.name === 'notify_approved' ? { ...h, failure_policy: 'fail_closed' } : { ...h, budget: { cpu_ms: 200, rows: 0, outbound_calls: 0 } }))
  const put = await api.put(`/projects/${id}/behavior/hooks`, { hooks, expected_version: cur.version })
  expect(put.status(), await put.text()).toBe(200)
  await page.getByRole('button', { name: 'Reload' }).count() // no-op: conflict banner only after the next save
  await match.getByLabel('CPU budget (ms)').fill('300')
  await save(page)
  await expect(page.getByTestId('conflict')).toBeVisible()
  await page.getByTestId('conflict').getByRole('button', { name: 'Reload' }).click()
  await expect(page.getByTestId('conflict')).toHaveCount(0)
  const notify = hook(page, 'notify_approved')
  await expect(notify.getByTestId('hook-issues')).toContainText('after_commit runs after the data is saved: it cannot be fail_closed')
  await notify.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(notify.getByTestId('field-error')).toContainText('cannot be fail_closed')
  await expect(notify.getByLabel('If the hook fails').locator('option')).toHaveText(['fail_open', 'fallback'])

  // remove the hook, save, reload: gone
  await notify.getByRole('button', { name: 'Remove hook notify_approved' }).click()
  await save(page)
  await expect(page.getByTestId('save-note')).toContainText('Saved')
  await page.reload()
  await expect(page.getByTestId('hook-row')).toHaveCount(1)
  await expect(page.getByTestId('issue-summary')).toHaveCount(0)
})

test('hooks: empty and error states', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Empty Hooks')
  await page.goto(`/#/p/${id}/hooks`)
  await expect(page.getByTestId('hooks-empty')).toBeVisible()
  await expect(page.getByText('A hook is where your own code plugs into the generated backend').first()).toBeVisible()
  await expect(page.getByText('Add an entity in the data model first')).toBeVisible()
  await page.route('**/behavior/hooks', (route) =>
    route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ code: 'boom', message: 'Backend exploded' }) }),
  )
  await page.reload()
  await expect(page.getByRole('alert').filter({ hasText: 'We could not load hooks' })).toBeVisible()
  await page.unroute('**/behavior/hooks')
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByTestId('hooks-empty')).toBeVisible()
})
