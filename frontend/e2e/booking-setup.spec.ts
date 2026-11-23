/** CP-6F/6I: Operate > Booking admin ("booking setup"). The rules and kinds of the booking pack are edited and saved in the real spec
 *  (builder API); resources and availability come from the mocked preview app behind the preview sign-in (see preview-mock.ts).
 *  Not run by its author; run with `npx playwright test e2e/booking-setup.spec.ts`. */
import { expect, test } from '@playwright/test'
import { createProjectViaApi, expectAxeClean, importFixture, signedInUser, watchProblems } from './helpers'
import { BEARER, mockPreviewSession, signInPreview } from './preview-mock'

test('booking admin: save new hold and cancellation rules, create a resource, disable it, check availability', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Booking Setup')
  await importFixture(api, id, 'booking_clinic.json')

  type Res = { id: string; kind: string; mode: string; name: string; timezone: string; slot_minutes: number | null; capacity: number | null; min_minutes: number | null; max_minutes: number | null; active: boolean; schedule: unknown }
  const resources: Res[] = []
  const seen = await mockPreviewSession(page, id, (r) => {
    if (r.method === 'GET' && r.path === '/booking/resources') return { json: { items: resources, total: resources.length, limit: 200, offset: 0 } }
    if (r.method === 'POST' && r.path === '/booking/resources') {
      const b = r.body as { kind: string; name: string; timezone?: string }
      resources.push({ id: 'r1', kind: b.kind, mode: 'slot', name: b.name, timezone: b.timezone ?? 'Europe/Berlin', slot_minutes: 30, capacity: null, min_minutes: null, max_minutes: null, active: true, schedule: { mon: [{ start: '09:00', end: '12:00' }] } })
      return { status: 201, json: resources[0] }
    }
    if (r.method === 'PATCH' && r.path === '/booking/resources/r1') { Object.assign(resources[0], r.body); return { json: resources[0] } }
    if (r.method === 'GET' && r.path === '/booking/resources/r1/availability') {
      const from = new URLSearchParams(r.search).get('from')!
      return { json: { resource_id: 'r1', timezone: 'Europe/Berlin', slot_minutes: 30, slots: [
        { starts_at: `${from}T09:00:00+00:00`, ends_at: `${from}T09:30:00+00:00`, free: true },
        { starts_at: `${from}T09:30:00+00:00`, ends_at: `${from}T10:00:00+00:00`, free: false },
      ] } }
    }
    return undefined
  })
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/bookingadmin`)
  await expect(page.getByRole('heading', { level: 1, name: 'Booking admin' })).toBeVisible()

  // Rules and kinds come from the real spec.
  await expect(page.getByTestId('bkadm-rules-form')).toBeVisible()
  await expect(page.getByTestId('bkadm-kind')).toHaveCount(3)
  await expect(page.getByLabel('Hold time (seconds)')).toHaveValue('120')
  await page.getByLabel('Hold time (seconds)').fill('0')
  await page.getByTestId('bkadm-rules-save').click()
  await expect(page.getByTestId('bkadm-field-error').first()).toBeVisible() // refused locally: 1 to 86400
  await page.getByLabel('Hold time (seconds)').fill('300')
  await page.getByLabel('Late cancellation fee (minor units, e.g. cents)').fill('3000')
  await expect(page.getByTestId('bkadm-cancel-summary')).toContainText('30.00')
  await page.getByTestId('bkadm-rules-save').click()
  await expect(page.getByTestId('bkadm-rules-notice')).toContainText('Saved.')
  const packs = await (await api.get(`/projects/${id}/behavior/packs`)).json()
  expect(packs.packs.booking.hold_ttl_seconds).toBe(300)
  expect(packs.packs.booking.cancellation.fee_minor).toBe(3000)
  expect(packs.packs.booking.kinds).toHaveLength(3)

  // The resources section waits for the preview sign-in.
  expect(seen).toHaveLength(0)
  await signInPreview(page)
  await expect(page.getByTestId('bkadm-res-empty')).toBeVisible()
  await page.getByTestId('bkadm-create-name').fill('Dr Weber')
  await page.getByTestId('bkadm-create-submit').click()
  await expect(page.getByTestId('bkadm-res-notice')).toHaveText('Created Dr Weber.')
  expect(seen.find((s) => s.method === 'POST' && s.path === '/booking/resources')!.body).toMatchObject({ kind: 'practitioner', name: 'Dr Weber' })
  await expect(page.getByTestId('bkadm-res-row')).toHaveCount(1)
  await expect(page.getByTestId('bkadm-res-row')).toContainText('slot')

  await page.getByTestId('bkadm-av-check').click()
  await expect(page.getByTestId('bkadm-av-day')).toHaveCount(1)
  await expect(page.getByTestId('bkadm-av-free')).toContainText('1:')

  // Disable asks first.
  await page.getByRole('button', { name: 'Disable Dr Weber' }).click()
  await expect(page.getByTestId('bkadm-disable-confirm')).toBeVisible()
  expect(seen.some((s) => s.method === 'PATCH')).toBe(false)
  await page.getByTestId('bkadm-disable-yes').click()
  await expect(page.getByTestId('bkadm-res-notice')).toHaveText('Dr Weber disabled.')
  expect(seen.find((s) => s.method === 'PATCH')!.body).toEqual({ active: false })
  await expect(page.getByTestId('bkadm-res-row')).toHaveAttribute('data-active', 'false')
  expect(seen.every((s) => s.auth === BEARER)).toBe(true)

  await expectAxeClean(page, 'booking admin page')
  watch.assertNone()
})
