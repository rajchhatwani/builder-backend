/** CP-6G/6I: Operate > Matching. Rank candidates for a request, offer it to the best one (with a confirmation), accept the offer.
 *  The generated project's API is mocked (see preview-mock.ts) behind the preview sign-in; the project is real.
 *  Not run by its author; run with `npx playwright test e2e/matching.spec.ts`. */
import { expect, test } from '@playwright/test'
import { createProjectViaApi, expectAxeClean, signedInUser, watchProblems } from './helpers'
import { BEARER, mockPreviewSession, signInPreview } from './preview-mock'

test('matching: rank, assign the best candidate, accept the offer', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Matching Project')

  type Asg = { id: string; request_ref: string; candidate_id: string; status: string; score: number; distance_m: number; offered_at: string; expires_at: string; decided_at: string | null }
  const asg: Asg[] = []
  const ranked = [
    { candidate_id: 'van-1', score: 812, distance_m: 640, parts: { distance: 500, load: 200, rating: 112 } },
    { candidate_id: 'van-2', score: 455, distance_m: 5200, parts: { distance: 200, load: 150, rating: 105 } },
  ]
  const seen = await mockPreviewSession(page, id, (r) => {
    if (r.method === 'GET' && r.path === '/matching/assignments') {
      const st = new URLSearchParams(r.search).get('status')
      const items = asg.filter((a) => !st || a.status === st)
      return { json: { items, total: items.length, limit: 100, offset: 0 } }
    }
    if (r.method === 'POST' && r.path === '/matching/rank') return { json: { items: ranked, excluded: [{ candidate_id: 'van-3', reason: 'at capacity' }] } }
    if (r.method === 'POST' && r.path === '/matching/assignments') {
      const b = r.body as { request_ref: string }
      asg.push({ id: 'as1', request_ref: b.request_ref, candidate_id: 'van-1', status: 'offered', score: 812, distance_m: 640, offered_at: '2026-11-22T10:00:00Z', expires_at: '2026-11-22T10:15:00Z', decided_at: null })
      return { status: 201, json: asg[0] }
    }
    if (r.method === 'POST' && r.path === '/matching/assignments/as1/accept') { asg[0].status = 'accepted'; asg[0].decided_at = '2026-11-22T10:05:00Z'; return { json: asg[0] } }
    return undefined
  })
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/matching`)
  await expect(page.getByRole('heading', { level: 1, name: 'Matching' })).toBeVisible()
  expect(seen).toHaveLength(0)
  await signInPreview(page)
  await expect(page.getByTestId('assignments-empty')).toHaveText('No assignments yet.')

  // Bad input is refused locally.
  await page.getByTestId('rank-run').click()
  await expect(page.getByTestId('solve-error')).toContainText('Add at least one candidate')
  expect(seen.filter((s) => s.method === 'POST')).toHaveLength(0)

  await page.getByTestId('cands').fill('van-1, 40.0, -74.0, 2, 4500\nvan-2, 40.5, -74.0\nvan-3, 41.0, -74.0, 9')
  await page.getByTestId('request-ref').fill('R-9')
  await page.getByTestId('request-point-lat').fill('40.001')
  await page.getByTestId('request-point-lng').fill('-74.0')
  await page.getByTestId('rank-run').click()
  await expect(page.getByTestId('rank-row')).toHaveCount(2)
  await expect(page.getByTestId('rank-row').first()).toContainText('van-1')
  await expect(page.getByTestId('rank-excluded')).toHaveText('Excluded: van-3 (at capacity)')
  const rank = seen.find((s) => s.path === '/matching/rank')!
  expect(rank.body).toMatchObject({ point: { lat_micro: 40_001_000, lng_micro: -74_000_000 }, candidates: [{ id: 'van-1', lat_micro: 40_000_000, lng_micro: -74_000_000, load: 2, rating_milli: 4500 }, { id: 'van-2' }, { id: 'van-3', load: 9 }] })

  // Assign asks first.
  await page.getByTestId('assign-run').click()
  await expect(page.getByTestId('assign-confirm')).toContainText('Offer request R-9')
  expect(seen.some((s) => s.path === '/matching/assignments' && s.method === 'POST')).toBe(false)
  await page.getByTestId('assign-confirm-yes').click()
  await expect(page.getByTestId('solve-ok')).toHaveText('Offered to van-1 (score 812, 640 m).')
  await expect(page.getByTestId('assignment-row')).toHaveCount(1)
  await expect(page.getByTestId('assignment-state')).toHaveText('Offered')

  // Accept it.
  await page.getByRole('button', { name: 'Accept R-9' }).click()
  await expect(page.getByTestId('assignment-ok')).toHaveText('R-9: accepted.')
  await expect(page.getByTestId('assignment-state')).toHaveText('Accepted')
  await expect(page.getByRole('button', { name: 'Accept R-9' })).toHaveCount(0)
  expect(seen.every((s) => s.auth === BEARER)).toBe(true)

  await expectAxeClean(page, 'matching page')
  watch.assertNone()
})
