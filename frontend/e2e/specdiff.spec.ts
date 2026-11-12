/** F4-6: Build > Visual spec diff (new shell only). Snapshot, change nothing -> no differences; an older baseline -> the entity shows as added.
 *  Not run by the implementer; run with `npx playwright test e2e/specdiff.spec.ts`. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { createProjectViaApi, importInvoiceFlow, signedInUser, watchProblems } from './helpers'

const WEB = process.env.E2E_WEB_PORT ?? '5199'
test.use({
  storageState: { cookies: [], origins: [{ origin: `http://localhost:${WEB}`, localStorage: [{ name: 'ui.shell', value: 'v2' }] }] },
})

for (const viewport of [{ name: 'desktop', width: 1280, height: 800 }, { name: 'phone', width: 375, height: 700 }]) {
  test(`specdiff: snapshot shows no differences, an older baseline shows the entity as added (${viewport.name})`, async ({ page, request }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    const api = await signedInUser(page, request)
    const id = await createProjectViaApi(api, `Spec diff ${viewport.name}`)
    await importInvoiceFlow(api, id)
    const watch = watchProblems(page)
    await page.goto(`/#/p/${id}/specdiff`)
    await expect(page.getByRole('heading', { level: 1, name: 'Visual spec diff' })).toBeVisible()
    await expect(page.getByTestId('specdiff-nobaseline')).toBeVisible()

    await page.getByRole('button', { name: 'Save current spec as baseline' }).click()
    await expect(page.getByTestId('specdiff-empty')).toContainText('No differences')
    const axeEmpty = await new AxeBuilder({ page }).analyze()
    expect(axeEmpty.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), 'axe on the empty diff').toEqual([])

    // a baseline with one entity removed: that entity is now "added"
    const spec = (await (await api.get(`/projects/${id}/spec`)).json()) as { entities: { name: string }[] }
    const removed = spec.entities[0].name
    const older = { ...spec, entities: spec.entities.slice(1) }
    await page.getByLabel('Baseline spec (JSON)').fill(JSON.stringify(older))
    await page.getByRole('button', { name: 'Use as baseline' }).click()
    const result = page.getByTestId('specdiff-result')
    await expect(result).toContainText('+ Added')
    await expect(result).toContainText(removed)

    // an older version straight from the op-log, by a shareable link: before the first change everything is "added"
    await page.goto(`/#/p/${id}/specdiff?base=0`)
    await expect(page.getByTestId('specdiff-source')).toContainText('before the first change')
    await expect(page.getByTestId('specdiff-result')).toContainText(removed)
    await expect(page.getByTestId('specdiff-version')).toHaveValue('0')

    const axeDiff = await new AxeBuilder({ page }).analyze()
    expect(axeDiff.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), 'axe on the diff').toEqual([])
    watch.assertNone()
  })
}
