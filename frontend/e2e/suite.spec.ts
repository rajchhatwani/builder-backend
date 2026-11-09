/** F4-7: Secure > Suite identity (new shell only). Keycloak provider set via the API, suite realm path (a), save, reload.
 *  Not run by the implementer; run with `npx playwright test e2e/suite.spec.ts`. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { createProjectViaApi, signedInUser, watchProblems } from './helpers'

const WEB = process.env.E2E_WEB_PORT ?? '5199'
test.use({
  storageState: { cookies: [], origins: [{ origin: `http://localhost:${WEB}`, localStorage: [{ name: 'ui.shell', value: 'v2' }] }] },
})

for (const viewport of [{ name: 'desktop', width: 1280, height: 800 }, { name: 'phone', width: 375, height: 700 }]) {
  test(`suite identity: set suite, save, values persist (${viewport.name})`, async ({ page, request }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    const api = await signedInUser(page, request)
    const id = await createProjectViaApi(api, `Suite ${viewport.name}`)
    const saved = await api.put(`/projects/${id}/keycloak`, {})
    expect(saved.status(), await saved.text()).toBeLessThan(300)
    const sw = await api.post(`/projects/${id}/keycloak/enable`, { confirm: true })
    expect(sw.status(), await sw.text()).toBeLessThan(300)
    const watch = watchProblems(page)
    await page.goto(`/#/p/${id}/suite`)
    await expect(page.getByRole('heading', { level: 1, name: 'Suite identity' })).toBeVisible()
    await expect(page.getByTestId('suite-not-keycloak')).toHaveCount(0)

    await page.getByLabel('Part of a suite').check()
    await page.getByLabel('Suite id').fill('acme')
    await expect(page.getByTestId('suite-realm')).toHaveText('suite-acme')
    await page.getByLabel('Hub issuer (optional)').fill('https://id.acme.com/realms/suite-acme')
    await page.getByLabel('Join state').selectOption('planned')

    const axe = await new AxeBuilder({ page }).analyze()
    expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), 'axe on the suite page').toEqual([])

    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(page.getByTestId('suite-note')).toHaveText('Saved.')
    await expect(page.getByTestId('suite-issues')).toHaveCount(0)

    await page.reload()
    await expect(page.getByLabel('Part of a suite')).toBeChecked()
    await expect(page.getByLabel('Suite id')).toHaveValue('acme')
    await expect(page.getByLabel('Hub issuer (optional)')).toHaveValue('https://id.acme.com/realms/suite-acme')
    await expect(page.getByLabel('Join state')).toHaveValue('planned')
    await expect(page.getByTestId('suite-realm')).toHaveText('suite-acme')

    const kc = await (await api.get(`/projects/${id}/keycloak`)).json()
    expect(kc.mode).toBe('shared')
    expect(kc.realm).toBe('suite-acme')
    watch.assertNone()
  })
}
