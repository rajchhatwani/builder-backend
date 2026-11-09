/** F4-2: realtime updates. Two browser contexts, same user, same project. Page B sits on the History timeline;
 *  a spec change made from page A's session shows up in B within 3 s with no reload, and the header says "Live".
 *  NOT run by its author (ATLAS runs the Playwright stack). */
import { expect, test } from '@playwright/test'
import { createProjectViaApi, signInViaUi, signedInUser, watchProblems } from './helpers'

const WEB = process.env.E2E_WEB_PORT ?? '5199'
const V2 = { cookies: [], origins: [{ origin: `http://localhost:${WEB}`, localStorage: [{ name: 'ui.shell', value: 'v2' }] }] }
test.use({ storageState: V2 })

test('a change in one window appears in the other without reload', async ({ page, browser, request }) => {
  test.setTimeout(90_000)
  const api = await signedInUser(page, request) // window A
  const id = await createProjectViaApi(api, 'Realtime Project')

  const ctxB = await browser.newContext({ storageState: V2, viewport: { width: 1280, height: 800 } })
  const pageB = await ctxB.newPage()
  try {
    await signInViaUi(pageB, api.email)
    const watch = watchProblems(pageB)
    await pageB.goto(`/#/p/${id}/timeline`)
    await expect(pageB.getByRole('heading', { level: 1, name: 'History timeline' })).toBeVisible()
    await expect(pageB.getByTestId('timeline-empty')).toBeVisible()
    await expect(pageB.getByTestId('live-status')).toHaveText('Live')

    // window A opens the same project: B should list A as "also here"
    await page.goto(`/#/p/${id}/model`)
    await expect(page.getByTestId('live-status')).toHaveText('Live')

    const r = await api.post(`/projects/${id}/spec/ops`, { op_type: 'add_entity', payload: { entity: { name: 'Invoice' } } })
    expect(r.status(), await r.text()).toBe(201)

    // no reload on B
    await expect(pageB.getByTestId('timeline-list').getByRole('button', { name: /Version 1: Added entity Invoice/ })).toBeVisible({ timeout: 3_000 })
    await expect(pageB.getByTestId('timeline-empty')).toHaveCount(0)
    watch.assertNone()
  } finally {
    await ctxB.close()
  }
})
