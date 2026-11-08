/** F1-3: Build > Rules expression checker (new shell only). The page text must equal what the API says for the
 *  same input; autocomplete from the response fields; stale requests are cancelled; guards list with live badges.
 *  Refresh baselines with `npx playwright test e2e/rules.spec.ts --update-snapshots`. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { createProjectViaApi, importBrokenInvoiceFlow, importInvoiceFlow, signedInUser, watchProblems, type Api } from './helpers'

const WEB = process.env.E2E_WEB_PORT ?? '5199'
test.use({
  storageState: { cookies: [], origins: [{ origin: `http://localhost:${WEB}`, localStorage: [{ name: 'ui.shell', value: 'v2' }] }] },
})

const editor = (page: Page) => page.getByRole('textbox', { name: 'Expression' })
const combo = (page: Page) => page.getByRole('combobox', { name: 'Expression' })

async function apiCheck(api: Api, id: string, entity: string, expression: string) {
  const r = await api.post(`/projects/${id}/behavior/expressions/check`, { entity, expression, expect: 'bool' })
  expect(r.status(), await r.text()).toBe(200)
  return (await r.json()) as { ok: boolean; type: string | null; error: { message: string; pos: number } | null; fields: { name: string }[] }
}

test('rules: an invalid expression shows the same error as the API, with the position marked', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Rules Errors')
  await importInvoiceFlow(api, id)
  const watch = watchProblems(page)
  await page.goto(`/#/p/${id}/rules`)
  await expect(page.getByRole('heading', { level: 1, name: 'Rules' })).toBeVisible()
  await expect(page.getByText('nothing you type here is saved')).toBeVisible()

  for (const [input, marked] of [
    ['bogus_field > 1', 'bogus_field'],
    ['amount <= ', ''],
    ['amount + 1', null], // a number, not a true/false expression
    ['amount > 5 and', ''],
  ] as const) {
    await editor(page).fill(input)
    await expect(page.getByTestId('rules-error')).toBeVisible()
    const direct = await apiCheck(api, id, 'Invoice', input)
    expect(direct.ok, input).toBe(false)
    await expect(page.getByTestId('rules-error')).toHaveText(direct.error!.message)
    await expect(page.getByTestId('rules-type')).toHaveCount(0)
    if (marked !== null) await expect(page.getByTestId('rules-mark')).toHaveText(marked === '' ? '​' : marked)
  }

  // an accepted expression: green chip, no error, no mark
  await editor(page).fill('amount > 5 and amount < 100')
  await expect(page.getByTestId('rules-type')).toHaveText('true/false expression')
  await expect(page.getByTestId('rules-error')).toHaveCount(0)
  await expect(page.getByTestId('rules-mark')).toHaveCount(0)
  expect((await apiCheck(api, id, 'Invoice', 'amount > 5 and amount < 100')).type).toBe('bool')

  // empty input: no request result, a hint
  await editor(page).fill('')
  await expect(page.getByTestId('rules-result')).toContainText('Type an expression to check it.')
  watch.assertNone()
})

test('rules: field autocomplete (keyboard and mouse), fields come from the API', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Rules Complete')
  await importInvoiceFlow(api, id)
  await page.goto(`/#/p/${id}/rules`)
  const apiFields = (await apiCheck(api, id, 'Invoice', 'true')).fields.map((f) => f.name).sort()
  expect(apiFields.length).toBeGreaterThanOrEqual(4)
  await expect(page.getByTestId('rules-fields').locator('li')).toHaveCount(apiFields.length)

  const box = editor(page)
  const list = page.getByRole('listbox', { name: 'Fields' })
  await expect(list).toBeHidden()
  await expect(combo(page)).toHaveAttribute('aria-expanded', 'false')

  // Ctrl+Space lists every field; arrows move; Enter inserts
  await box.click()
  await page.keyboard.press('Control+Space')
  await expect(list).toBeVisible()
  await expect(combo(page)).toHaveAttribute('aria-expanded', 'true')
  await expect(list.getByRole('option')).toHaveText(apiFields.map((n) => new RegExp(`^${n}`)))
  await expect(list.getByRole('option').first()).toHaveAttribute('aria-selected', 'true')
  await page.keyboard.press('ArrowDown')
  await expect(list.getByRole('option').nth(1)).toHaveAttribute('aria-selected', 'true')
  await expect(box).toHaveAttribute('aria-activedescendant', /-1$/)
  await page.keyboard.press('ArrowUp')
  await page.keyboard.press('ArrowUp') // wraps to the last one
  await expect(list.getByRole('option').last()).toHaveAttribute('aria-selected', 'true')
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await expect(box).toHaveValue(apiFields[1])
  await expect(list).toBeHidden()

  // a prefix after an operator: filtered, Escape closes without changing the text, Enter completes
  await box.fill('')
  await box.pressSequentially('amount > 1 and st')
  await expect(list.getByRole('option')).toHaveText([/^status/])
  await page.keyboard.press('Escape')
  await expect(list).toBeHidden()
  await expect(box).toHaveValue('amount > 1 and st')
  await box.pressSequentially('a')
  await expect(list).toBeVisible()
  await page.keyboard.press('Enter')
  await expect(box).toHaveValue('amount > 1 and status')

  // mouse: click an option
  await box.fill('')
  await box.pressSequentially('po_')
  await list.getByRole('option', { name: /^po_amount/ }).click()
  await expect(box).toHaveValue('po_amount')
  // nothing matches: no list
  await box.pressSequentially(' + zz')
  await expect(list).toBeHidden()
})

test('rules: typing is debounced and a slow, stale answer never replaces the newest one', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Rules Stale')
  await importInvoiceFlow(api, id)
  const seen: string[] = []
  await page.route('**/behavior/expressions/check', async (route) => {
    const expression: string = route.request().postDataJSON().expression
    seen.push(expression)
    if (expression === 'amount > 1') await new Promise((r) => setTimeout(r, 1500)) // answer arrives long after the next keystrokes
    await route.continue()
  })
  await page.goto(`/#/p/${id}/rules`)
  await expect(page.getByTestId('rules-fields').locator('li').first()).toBeVisible()
  seen.length = 0

  // fast typing: one request, not one per character
  await editor(page).pressSequentially('amount > 5', { delay: 20 })
  await expect(page.getByTestId('rules-type')).toBeVisible()
  expect(seen.filter((e) => e !== 'true')).toEqual(['amount > 5'])

  // slow first answer, then a different text: the page shows the answer for the newest text
  await editor(page).fill('amount > 1')
  await expect.poll(() => seen.includes('amount > 1')).toBe(true)
  await editor(page).fill('amount > 1 and bogus')
  const direct = await apiCheck(api, id, 'Invoice', 'amount > 1 and bogus')
  await expect(page.getByTestId('rules-error')).toHaveText(direct.error!.message)
  await page.waitForTimeout(1800) // the stale answer has now arrived (or was cancelled): it must not show
  await expect(page.getByTestId('rules-error')).toHaveText(direct.error!.message)
  await expect(page.getByTestId('rules-type')).toHaveCount(0)
})

test('rules: guards of the state machines with a live badge each; broken ones show the API message', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Rules Guards')
  await importBrokenInvoiceFlow(api, id)
  await page.goto(`/#/p/${id}/rules`)
  const guards = page.getByTestId('rules-guards').locator('li')
  await expect(guards).toHaveCount(3)
  await expect(page.getByTestId('rules-guard-summary')).toHaveText('2 of 3 guards are broken.')
  const states: Record<string, string> = { 'Invoice/approve': 'broken', 'Invoice/auto_approve': 'broken', 'Invoice/needs_approval': 'ok' }
  for (const [key, state] of Object.entries(states)) {
    const row = page.locator(`[data-guard="${key}"]`)
    await expect(row).toHaveAttribute('data-state', state)
    await expect(row).toContainText(state === 'ok' ? 'Accepted' : 'Broken')
    const when = (await row.locator('code').textContent())!
    const direct = await apiCheck(api, id, 'Invoice', when)
    if (state === 'broken') await expect(row).toContainText(direct.error!.message)
    else expect(direct.ok).toBe(true)
  }
  await expect(page.getByRole('link', { name: 'Open the state machines page' })).toHaveAttribute('href', `#/p/${id}/machines`)

  // "Try it" loads the guard into the editor and checks it
  await page.locator('[data-guard="Invoice/approve"]').getByRole('button', { name: /^Try it/ }).click()
  await expect(editor(page)).toHaveValue('bogus_field > 1')
  await expect(page.getByTestId('rules-error')).toContainText("unknown field 'bogus_field'")
})

test('rules: no entities, no guards, and error states', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Rules Empty')
  await page.goto(`/#/p/${id}/rules`)
  await expect(page.getByTestId('rules-empty')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open the data model' })).toHaveAttribute('href', `#/p/${id}/model`)

  const r = await api.post(`/projects/${id}/entities`, { name: 'Item' })
  expect(r.status(), await r.text()).toBe(201)
  await page.reload()
  await expect(page.getByTestId('rules-no-guards')).toBeVisible()
  await expect(editor(page)).toBeVisible()

  // the check endpoint failing is reported, not swallowed
  await page.route('**/behavior/expressions/check', (route) =>
    route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ code: 'boom', message: 'Checker exploded' }) }),
  )
  await editor(page).fill('1 = 1')
  await expect(page.getByTestId('rules-result')).toContainText('The check could not run: Checker exploded')
  await page.unroute('**/behavior/expressions/check')

  // loading error + retry
  await page.route('**/behavior/state-machines', (route) =>
    route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ code: 'boom', message: 'Backend exploded' }) }),
  )
  await page.reload()
  await expect(page.getByRole('alert').filter({ hasText: 'We could not load the rules page' })).toBeVisible()
  await expect(page.getByText('Backend exploded')).toBeVisible()
  await page.unroute('**/behavior/state-machines')
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(editor(page)).toBeVisible()
})

test('rules: screenshots and axe (invalid expression, autocomplete open, guards)', async ({ page, request }, info) => {
  test.setTimeout(120_000)
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Rules Visual')
  await importBrokenInvoiceFlow(api, id)
  await page.goto(`/#/p/${id}/rules`)
  const mask = [page.locator('nav[data-shell="v2"] .muted, nav[data-shell="v2"] [data-testid=shell-project]')]
  const axeNow = async (label: string) => {
    const axe = await new AxeBuilder({ page }).analyze()
    expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), `axe ${label} on ${info.project.name}`).toEqual([])
  }
  await expect(page.getByTestId('rules-guard-summary')).toHaveText('2 of 3 guards are broken.')
  await editor(page).fill('amount > 10 and bogus_field < 3')
  await expect(page.getByTestId('rules-error')).toBeVisible()
  await page.waitForTimeout(400)
  await expect.soft(page).toHaveScreenshot('rules-invalid.png', { mask })
  await axeNow('invalid')

  await editor(page).fill('')
  await editor(page).pressSequentially('a')
  await expect(page.getByRole('listbox', { name: 'Fields' })).toBeVisible()
  await page.waitForTimeout(300)
  await expect.soft(page).toHaveScreenshot('rules-autocomplete.png', { mask })
  await axeNow('autocomplete open')

  await editor(page).fill('amount > 10')
  await expect(page.getByTestId('rules-type')).toBeVisible()
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'))
  await axeNow('dark, accepted')
})
