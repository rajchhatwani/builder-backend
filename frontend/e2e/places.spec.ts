/** CP-6G/6I: Operate > Places and geofences. Create a place, edit it, filter, and see the table follow.
 *  The generated project's API is mocked (see preview-mock.ts) behind the preview sign-in; the project is real.
 *  Not run by its author; run with `npx playwright test e2e/places.spec.ts`. */
import { expect, test } from '@playwright/test'
import { createProjectViaApi, expectAxeClean, signedInUser, watchProblems } from './helpers'
import { BEARER, mockPreviewSession, signInPreview } from './preview-mock'

test('places: create a place, edit it, filter by kind', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Places Project')

  type Place = { id: string; name: string; kind: string | null; lat_micro: number; lng_micro: number; lat: string; lng: string }
  const places: Place[] = []
  const deg = (m: number) => (m / 1_000_000).toFixed(6)
  const seen = await mockPreviewSession(page, id, (r) => {
    if (r.method === 'GET' && r.path === '/geo/places') {
      const kind = new URLSearchParams(r.search).get('kind')
      const items = places.filter((p) => !kind || p.kind === kind)
      return { json: { items, total: items.length, limit: 100, offset: 0 } }
    }
    if (r.method === 'GET' && r.path === '/geo/geofences') return { json: { items: [], total: 0, limit: 100, offset: 0 } }
    if (r.method === 'GET' && r.path === '/geo/events') return { json: { items: [], total: 0, limit: 50, offset: 0 } }
    if (r.method === 'GET' && r.path === '/location/positions') return { json: { items: [], truncated: false } }
    if (r.method === 'POST' && r.path === '/geo/places') {
      const b = r.body as { name: string; kind: string | null; lat_micro: number; lng_micro: number }
      const p: Place = { id: `pl${places.length + 1}`, ...b, lat: deg(b.lat_micro), lng: deg(b.lng_micro) }
      places.push(p)
      return { status: 201, json: p }
    }
    const put = /^\/geo\/places\/([^/]+)$/.exec(r.path)
    if (r.method === 'PUT' && put) {
      const p = places.find((x) => x.id === put[1])!
      const b = r.body as { name: string; kind: string | null; lat_micro: number; lng_micro: number }
      Object.assign(p, b, { lat: deg(b.lat_micro), lng: deg(b.lng_micro) })
      return { json: p }
    }
    return undefined
  })
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/places`)
  await expect(page.getByRole('heading', { level: 1, name: 'Places and geofences' })).toBeVisible()
  expect(seen).toHaveLength(0)
  await signInPreview(page)
  await expect(page.getByTestId('places-empty')).toBeVisible()

  // Nothing is sent for an incomplete form.
  await page.getByTestId('place-save').click()
  await expect(page.getByTestId('place-save-error')).toHaveText('Give the place a name.')
  expect(seen.filter((s) => s.method === 'POST')).toHaveLength(0)

  // Create (degrees in, integer micro-degrees out).
  await page.getByTestId('place-name').fill('Head office')
  await page.getByTestId('place-kind').fill('office')
  await page.getByTestId('place-point-lat').fill('40.7128')
  await page.getByTestId('place-point-lng').fill('-74.006')
  await page.getByTestId('place-save').click()
  await expect(page.getByTestId('place-save-ok')).toHaveText('Place created.')
  expect(seen.find((s) => s.method === 'POST' && s.path === '/geo/places')!.body).toEqual({ name: 'Head office', kind: 'office', lat_micro: 40_712_800, lng_micro: -74_006_000 })
  await expect(page.getByTestId('place-row')).toHaveCount(1)
  await expect(page.getByTestId('place-row')).toContainText('Head office')
  await expect(page.getByTestId('place-name')).toHaveValue('')

  // Edit it: the form is filled from the row, the save is a PUT.
  await page.getByRole('button', { name: 'Edit Head office' }).click()
  await expect(page.getByTestId('place-name')).toHaveValue('Head office')
  await expect(page.getByTestId('place-point-lat')).toHaveValue('40.7128')
  await page.getByTestId('place-name').fill('HQ')
  await page.getByTestId('place-point-lat').fill('41.5')
  await page.getByTestId('place-save').click()
  await expect(page.getByTestId('place-save-ok')).toHaveText('Place updated.')
  expect(seen.find((s) => s.method === 'PUT' && s.path === '/geo/places/pl1')!.body).toEqual({ name: 'HQ', kind: 'office', lat_micro: 41_500_000, lng_micro: -74_006_000 })
  await expect(page.getByTestId('place-row')).toContainText('HQ')
  await expect(page.getByTestId('place-row')).toContainText('41.500000')

  // Filter by kind asks the server.
  await page.getByTestId('place-filter-kind').fill('depot')
  await page.getByTestId('place-filter-apply').click()
  await expect(page.getByTestId('places-empty')).toHaveText('No places of kind depot.')
  expect(seen.some((s) => s.path === '/geo/places' && s.search.includes('kind=depot'))).toBe(true)
  expect(seen.every((s) => s.auth === BEARER)).toBe(true)

  await expectAxeClean(page, 'places page')
  watch.assertNone()
})
