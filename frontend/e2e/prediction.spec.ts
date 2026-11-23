/** CP-6G/6I: Operate > Prediction. Record a prediction, add the actual outcome, read the accuracy statistics.
 *  The generated project's API is mocked (see preview-mock.ts) behind the preview sign-in; the project is real.
 *  Not run by its author; run with `npx playwright test e2e/prediction.spec.ts`. */
import { expect, test } from '@playwright/test'
import { createProjectViaApi, expectAxeClean, signedInUser, watchProblems } from './helpers'
import { BEARER, mockPreviewSession, signInPreview } from './preview-mock'

test('prediction: predict, record the actual, see the accuracy', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Prediction Project')

  type Rec = { id: string; kind: string; subject_ref: string; model_id: string; unit: string; value: number; low: number; high: number; features: Record<string, unknown>; actual: number | null; actual_at: string | null; created_at: string }
  const recs: Rec[] = []
  const seen = await mockPreviewSession(page, id, (r) => {
    if (r.method === 'GET' && r.path === '/prediction/records') return { json: { items: recs, total: recs.length, limit: 100, offset: 0 } }
    if (r.method === 'GET' && r.path === '/prediction/stats') {
      const withActual = recs.filter((x) => x.actual !== null)
      const covered = withActual.filter((x) => x.actual! >= x.low && x.actual! <= x.high).length
      const mae = withActual.length ? Math.round((withActual.reduce((s, x) => s + Math.abs(x.actual! - x.value), 0) / withActual.length) * 1000) : null
      return { json: { logged: recs.length, with_actual: withActual.length, mae_milli: mae, abs_error_sum: 0, covered, coverage_bp: withActual.length ? Math.round((covered * 10000) / withActual.length) : null } }
    }
    if (r.method === 'POST' && r.path === '/prediction/predict') {
      const b = r.body as { kind: string; subject_ref: string; features: Record<string, unknown> }
      recs.push({ id: 'pr1', kind: b.kind, subject_ref: b.subject_ref, model_id: 'fake-v1', unit: 'min', value: 20, low: 15, high: 25, features: b.features, actual: null, actual_at: null, created_at: '2026-11-22T10:00:00Z' })
      return { status: 201, json: recs[0] }
    }
    if (r.method === 'POST' && r.path === '/prediction/records/pr1/actual') { recs[0].actual = (r.body as { actual: number }).actual; recs[0].actual_at = '2026-11-22T11:00:00Z'; return { json: recs[0] } }
    return undefined
  })
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/prediction`)
  await expect(page.getByRole('heading', { level: 1, name: 'Prediction' })).toBeVisible()
  expect(seen).toHaveLength(0)
  await signInPreview(page)
  await expect(page.getByTestId('records-empty')).toBeVisible()
  await expect(page.getByTestId('stats-empty')).toBeVisible()

  await page.getByTestId('predict-run').click()
  await expect(page.getByTestId('predict-error')).toContainText('Kind: 1-32 characters')
  expect(seen.filter((s) => s.method === 'POST')).toHaveLength(0)

  await page.getByTestId('predict-kind').fill('delivery_time')
  await page.getByTestId('predict-subject').fill('order-42')
  await page.getByTestId('predict-features').fill('distance_m = 1200\nrush = true')
  await page.getByTestId('predict-run').click()
  await expect(page.getByTestId('predict-ok')).toHaveText('Prediction recorded.')
  await expect(page.getByTestId('predict-result')).toHaveText('Predicted 20 min (interval 15 to 25) by fake-v1.')
  expect(seen.find((s) => s.path === '/prediction/predict')!.body).toEqual({ kind: 'delivery_time', subject_ref: 'order-42', features: { distance_m: 1200, rush: true } })
  await expect(page.getByTestId('record-row')).toHaveCount(1)
  await expect(page.getByTestId('stat-logged')).toHaveText('1')
  await expect(page.getByTestId('stat-with-actual')).toHaveText('0')

  // The actual outcome: 22 is inside the interval, so coverage is full.
  await page.getByLabel('Actual value for order-42').fill('22')
  await page.getByRole('button', { name: 'Record actual for order-42' }).click()
  await expect(page.getByTestId('record-row')).toContainText('22')
  await expect(page.getByTestId('actual-input')).toHaveCount(0)
  expect(seen.find((s) => s.path === '/prediction/records/pr1/actual')!.body).toEqual({ actual: 22 })
  await expect(page.getByTestId('stat-with-actual')).toHaveText('1')
  await expect(page.getByTestId('stat-coverage')).toContainText('(1 of 1)')
  expect(seen.every((s) => s.auth === BEARER)).toBe(true)

  await expectAxeClean(page, 'prediction page')
  watch.assertNone()
})
