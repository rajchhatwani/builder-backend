/** F5-2: Operate > Map (new shell). Sign in to the preview, load live positions, open a subject's details.
 *  The project API is mocked (see preview-mock.ts). Not run by its author; run with `npx playwright test e2e/map.spec.ts`. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { createProjectViaApi, signedInUser, watchProblems } from './helpers'
import { BEARER, SESSION, mockPreviewSession, signInPreview } from './preview-mock'

test('map: load positions, geofence and place, open a subject and see where it is', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Map Project')

  const ago = (s: number) => new Date(Date.now() - s * 1000).toISOString()
  const pos = (sid: string, lat: number, lng: number, seconds: number) => ({
    subject_id: sid, subject_kind: 'courier', lat_micro: lat, lng_micro: lng, lat: '', lng: '', seq: 3, recorded_at: ago(seconds), updated_at: ago(seconds),
  })
  const POS = [pos('van-1', 40_000_000, -74_000_000, 10), pos('van-2', 41_000_000, -73_000_000, 15)]
  const FENCES = [{ id: 'g1', name: 'Depot', shape: 'circle', center: { lat_micro: 40_000_000, lng_micro: -74_000_000 }, radius_m: 500, vertices: null }]
  const PLACES = [{ id: 'pl1', name: 'HQ', kind: 'office', lat_micro: 40_500_000, lng_micro: -73_500_000, lat: '', lng: '' }]
  const ASG = [{ id: 'as1', request_ref: 'R-9', candidate_id: 'van-1', status: 'offered', score: 812, distance_m: 640, expires_at: ago(-60) }]
  const seen = await mockPreviewSession(page, id, (r) => {
    if (r.method !== 'GET') return undefined
    if (r.path === '/location/positions') return { json: { items: POS, truncated: false } }
    if (r.path === '/geo/geofences') return { json: { items: FENCES, total: 1, limit: 200, offset: 0 } }
    if (r.path === '/geo/places') return { json: { items: PLACES, total: 1, limit: 200, offset: 0 } }
    if (r.path === '/matching/assignments') return { json: { items: ASG, total: 1, limit: 100, offset: 0 } }
    return undefined
  })
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/map`)
  await expect(page.getByTestId('map-page')).toBeVisible()
  expect(seen).toHaveLength(0) // nothing is asked of the project API before the preview sign-in
  await signInPreview(page)

  await expect(page.getByTestId('map-list-item')).toHaveCount(2)
  await expect(page.getByTestId('map-marker')).toHaveCount(2)
  await expect(page.getByTestId('map-fence-circle')).toHaveCount(1)
  await expect(page.getByTestId('map-place')).toHaveCount(1)
  await expect(page.getByTestId('map-updated')).toBeVisible()
  await expect(page.locator('[data-testid="map-marker"][data-subject="van-1"]')).toHaveAttribute('data-freshness', 'fresh')

  // What the page asked the project API for.
  const pos1 = seen.find((s) => s.path === '/location/positions')!
  expect(pos1.search).toContain('min_lat_micro=-90000000&min_lng_micro=-180000000&max_lat_micro=90000000&max_lng_micro=180000000&limit=500')
  expect(seen.some((s) => s.path === '/geo/geofences')).toBe(true)
  expect(seen.some((s) => s.path === '/geo/places')).toBe(true)
  expect(seen.find((s) => s.path === '/matching/assignments')!.search).toContain('status=offered')
  expect(seen.every((s) => s.method === 'GET' && s.auth === BEARER && s.previewToken === SESSION.previewToken && !s.search.includes(SESSION.jwt))).toBe(true)

  // Open van-1 from the list: inside the Depot fence, with an open offer.
  await page.locator('[data-testid="map-list-item"][data-subject="van-1"]').click()
  const details = page.getByTestId('map-details')
  await expect(details).toBeVisible()
  await expect(details.getByRole('heading', { name: 'van-1' })).toBeVisible()
  await expect(details).toContainText('Position 40.000000, -74.000000, sequence 3')
  await expect(page.getByTestId('map-details-fences')).toHaveText('Inside: Depot')
  await expect(page.getByTestId('map-assignment')).toHaveText('Request R-9: offered, 640 m away, score 812')
  await expect(page.locator('[data-testid="map-marker"][data-subject="van-1"]')).toHaveAttribute('aria-pressed', 'true')

  // Open van-2 from its marker on the canvas: outside every fence, no offers.
  await page.locator('[data-testid="map-marker"][data-subject="van-2"]').click()
  await expect(details.getByRole('heading', { name: 'van-2' })).toBeVisible()
  await expect(page.getByTestId('map-details-fences')).toHaveText('Inside no geofence.')
  await expect(page.getByTestId('map-details-assignments')).toContainText('No open assignment offers.')

  // Narrowing to the visible area re-queries with a smaller box (not the whole world).
  const before = seen.filter((s) => s.path === '/location/positions').length
  await page.getByTestId('map-load-area').click()
  await expect.poll(() => seen.filter((s) => s.path === '/location/positions').length).toBeGreaterThan(before)
  const last = seen.filter((s) => s.path === '/location/positions').at(-1)!
  expect(last.search).not.toContain('min_lat_micro=-90000000')
  await expect(page.getByTestId('map-list-item')).toHaveCount(2)

  await page.getByTestId('map-details-close').click()
  await expect(details).toHaveCount(0)

  const axe = await new AxeBuilder({ page }).analyze()
  expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), 'axe on the map page').toEqual([])
  watch.assertNone()
})
