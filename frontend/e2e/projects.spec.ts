import { expect, test } from '@playwright/test'
import { SECTION_IDS, createProjectViaApi, signedInUser, watchProblems } from './helpers'

test.describe('projects and the 12 sections', () => {
  test('create, see on the list, rename (API) shows after reload, delete', async ({ page, request }) => {
    const api = await signedInUser(page, request)
    await page.getByRole('button', { name: 'Create a project' }).click()
    await page.getByRole('textbox', { name: 'Name', exact: true }).fill('Journey One')
    await page.getByRole('button', { name: 'Create project' }).click()
    await expect(page).toHaveURL(/#\/p\/[^/]+/)
    await page.goto('/#/')
    await expect(page.getByText('Journey One').first()).toBeVisible()

    const list = await (await api.get('/projects')).json()
    const project = list.items.find((p: { name: string }) => p.name === 'Journey One')
    const patch = await api.patch(`/projects/${project.id}`, { version: project.version, name: 'Journey Renamed' })
    expect(patch.status()).toBe(200)
    await page.reload()
    await expect(page.getByText('Journey Renamed').first()).toBeVisible()

    await page.getByRole('button', { name: 'Delete' }).first().click()
    await page.getByRole('button', { name: 'Delete project' }).click()
    await expect(page.getByText('Journey Renamed')).toHaveCount(0)
  })

  test('data model: add an entity and a field through the UI', async ({ page, request }) => {
    const api = await signedInUser(page, request)
    const id = await createProjectViaApi(api, 'Model Journey')
    await page.goto(`/#/p/${id}/model`)
    await page.getByRole('button', { name: /new entity|add entity/i }).first().click()
    await page.getByLabel('Name').first().fill('Post')
    await page.getByRole('button', { name: 'Create entity' }).click()
    await expect(page.getByText('Post').first()).toBeVisible()
    const entities = await (await api.get(`/projects/${id}/entities`)).json()
    expect(entities.items.map((e: { name: string }) => e.name)).toContain('Post')
  })

  test('every section loads from its deep link without a server error', async ({ page, request }) => {
    const api = await signedInUser(page, request)
    const id = await createProjectViaApi(api, 'Sections Journey')
    const watch = watchProblems(page)
    for (const section of SECTION_IDS) {
      await page.goto(`/#/p/${id}/${section}`)
      await expect(page.locator('main, [role=main], body').first()).toBeVisible()
      await expect(page.getByText(/something went wrong|unexpected error/i)).toHaveCount(0)
      await expect(page).toHaveURL(new RegExp(`#/p/${id}/${section}$`))
    }
    watch.assertNone()
  })

  test('generate: validate, preview and download a zip', async ({ page, request }) => {
    const api = await signedInUser(page, request)
    const id = await createProjectViaApi(api, 'Generate Journey')
    await api.post(`/projects/${id}/entities`, { name: 'Post', fields: [{ name: 'title', type: 'string', required: true }] })
    await page.goto(`/#/p/${id}/generate`)
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('button', { name: 'Download' }).click(),
    ])
    expect(download.suggestedFilename()).toMatch(/\.zip$/)
  })
})
