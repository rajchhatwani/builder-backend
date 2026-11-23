/** CP-6G/6I: Operate > Route, ETA and geocode. Geocode an address, get a route and an ETA, measure a distance.
 *  The generated project's API is mocked (see preview-mock.ts) behind the preview sign-in; the project is real.
 *  Not run by its author; run with `npx playwright test e2e/routing.spec.ts`. */
import { expect, test } from '@playwright/test'
import { createProjectViaApi, expectAxeClean, signedInUser, watchProblems } from './helpers'
import { BEARER, mockPreviewSession, signInPreview } from './preview-mock'

test('routing: geocode, route, ETA and distance', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Routing Project')

  const seen = await mockPreviewSession(page, id, (r) => {
    if (r.method !== 'POST') return undefined
    if (r.path === '/geo/geocode') return { json: { lat: '40.712800', lng: '-74.006000', provider: 'fake' } }
    if (r.path === '/geo/route') return { json: { distance_m: 12_345, duration_s: 1_500, provider: 'fake' } }
    if (r.path === '/geo/eta') return { json: { distance_m: 12_345, duration_s: 1_500, provider: 'fake', arrives_at: '2026-12-01T09:25:00Z' } }
    if (r.path === '/geo/distance') return { json: { distance_m: 800 } }
    return undefined
  })
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/routing`)
  await expect(page.getByRole('heading', { level: 1, name: 'Route, ETA and geocode' })).toBeVisible()
  expect(seen).toHaveLength(0)
  await signInPreview(page)

  await page.getByTestId('geocode-run').click()
  await expect(page.getByTestId('geocode-error')).toHaveText('Enter an address.')
  expect(seen).toHaveLength(0)
  await page.getByTestId('geocode-address').fill('1 Main Street')
  await page.getByTestId('geocode-run').click()
  await expect(page.getByTestId('geocode-result')).toHaveText('Latitude 40.712800, longitude -74.006000 (provider: fake).')
  expect(seen[0].body).toEqual({ address: '1 Main Street' })

  await page.getByTestId('route-origin-lat').fill('40.7')
  await page.getByTestId('route-origin-lng').fill('-74.0')
  await page.getByTestId('route-dest-lat').fill('40.8')
  await page.getByTestId('route-dest-lng').fill('-73.9')
  await page.getByTestId('route-mode').selectOption('bike')
  await page.getByTestId('route-run').click()
  await expect(page.getByTestId('route-result')).toContainText('12.34 km (12345 m), 25 min 0 s')
  expect(seen.find((s) => s.path === '/geo/route')!.body).toEqual({ origin: { lat_micro: 40_700_000, lng_micro: -74_000_000 }, destination: { lat_micro: 40_800_000, lng_micro: -73_900_000 }, mode: 'bike' })

  await page.getByTestId('eta-origin-lat').fill('40.7')
  await page.getByTestId('eta-origin-lng').fill('-74.0')
  await page.getByTestId('eta-dest-lat').fill('40.8')
  await page.getByTestId('eta-dest-lng').fill('-73.9')
  await page.getByTestId('eta-run').click()
  await expect(page.getByTestId('eta-result')).toContainText('arrives 2026-12-01T09:25:00Z')
  expect(seen.find((s) => s.path === '/geo/eta')!.body).not.toHaveProperty('depart_at')

  await page.getByTestId('distance-a-lat').fill('0')
  await page.getByTestId('distance-a-lng').fill('0')
  await page.getByTestId('distance-b-lat').fill('0.0072')
  await page.getByTestId('distance-b-lng').fill('0')
  await page.getByTestId('distance-run').click()
  await expect(page.getByTestId('distance-result')).toHaveText('800 m (800 m) along the great circle.')
  expect(seen.every((s) => s.auth === BEARER)).toBe(true)

  await expectAxeClean(page, 'routing page')
  watch.assertNone()
})
