/** F5-3: Operate > Bookings (new shell). Sign in to the preview, hold a free slot, confirm it, then cancel it and see the recorded fee.
 *  The project API is mocked (see preview-mock.ts). Not run by its author; run with `npx playwright test e2e/bookings.spec.ts`. */
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { createProjectViaApi, signedInUser, watchProblems } from './helpers'
import { BEARER, SESSION, mockPreviewSession, signInPreview } from './preview-mock'


const RES = { id: 'r1', kind: 'practitioner', mode: 'slot', name: 'Dr A', timezone: 'UTC', slot_minutes: 30, capacity: 1, min_minutes: null, max_minutes: null, active: true }
const addDays = (date: string, n: number) => { const d = new Date(`${date}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10) }

test('bookings: hold a slot, confirm it, cancel it', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Bookings Project')

  // The page shows the week that contains "today" (resource zone is UTC); the slots are taken from the week the page asks for.
  let booking: Record<string, unknown> | null = null
  let slotKey = ''
  const slotIso = (date: string, hm: string) => `${date}T${hm}:00Z`
  const seen = await mockPreviewSession(page, id, (r) => {
    if (r.method === 'GET' && r.path === '/booking/resources') return { json: { items: [RES], total: 1, limit: 200, offset: 0 } }
    if (r.method === 'GET' && r.path === '/booking/resources/r1/availability') {
      const from = new URLSearchParams(r.search).get('from')!
      const day = addDays(from, 2) // Wednesday
      slotKey = `${day}|09:00`
      const taken = !!booking && (booking.status === 'held' || booking.status === 'confirmed')
      return { json: { resource_id: 'r1', timezone: 'UTC', slot_minutes: 30, slots: [
        { starts_at: slotIso(day, '09:00'), ends_at: slotIso(day, '09:30'), free: !taken },
        { starts_at: slotIso(day, '09:30'), ends_at: slotIso(day, '10:00'), free: true },
      ] } }
    }
    if (r.method === 'GET' && r.path === '/booking/bookings') return { json: { items: booking ? [booking] : [], total: booking ? 1 : 0, limit: 200, offset: 0 } }
    if (r.method === 'POST' && r.path === '/booking/bookings') {
      const b = r.body as { starts_at: string; ends_at: string; customer_ref?: string; notes?: string }
      booking = {
        id: 'bk1', resource_id: 'r1', resource_name: 'Dr A', kind: 'practitioner', mode: 'slot', status: 'held', starts_at: b.starts_at, ends_at: b.ends_at, quantity: 1,
        hold_expires_at: new Date(Date.now() + 15 * 60_000).toISOString(), customer_ref: b.customer_ref ?? null, notes: b.notes ?? null,
        cancel_fee_minor: null, fee_currency: null, cancelled_at: null, confirmed_at: null,
      }
      return { status: 201, json: booking }
    }
    if (r.method === 'POST' && r.path === '/booking/bookings/bk1/confirm') {
      booking = { ...booking!, status: 'confirmed', hold_expires_at: null, confirmed_at: new Date().toISOString() }
      return { json: booking }
    }
    if (r.method === 'POST' && r.path === '/booking/bookings/bk1/cancel') {
      booking = { ...booking!, status: 'cancelled', cancel_fee_minor: 2500, fee_currency: 'USD', cancelled_at: new Date().toISOString() }
      return { json: booking }
    }
    return undefined
  })
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/bookings`)
  await expect(page.getByTestId('bookings-page')).toBeVisible()
  expect(seen).toHaveLength(0)
  await signInPreview(page)

  await expect(page.getByTestId('bookings-tz')).toContainText('UTC')
  await expect(page.getByTestId('bookings-cell')).toHaveCount(2)
  const cell = () => page.locator(`[data-testid="bookings-cell"][data-key="${slotKey}"]`)
  await expect(cell()).toHaveAttribute('data-state', 'free')
  const av = seen.find((s) => s.path === '/booking/resources/r1/availability')!
  expect(av.search).toContain('include_taken=true')
  expect(seen.every((s) => s.auth === BEARER && s.previewToken === SESSION.previewToken && !s.search.includes(SESSION.jwt))).toBe(true)

  // Hold.
  await cell().click()
  await expect(page.getByTestId('bookings-selected')).toBeVisible()
  await page.getByTestId('bookings-customer').fill('ACME')
  await page.getByTestId('bookings-notes').fill('first visit')
  await page.getByTestId('bookings-hold').click()
  await expect(page.getByTestId('bookings-notice')).toContainText('Hold created for')
  const hold = seen.find((s) => s.method === 'POST' && s.path === '/booking/bookings')!
  const day = slotKey.split('|')[0]
  expect(hold.body).toMatchObject({ resource_id: 'r1', starts_at: `${day}T09:00:00Z`, ends_at: `${day}T09:30:00Z`, confirm: false, customer_ref: 'ACME', notes: 'first visit' })
  expect(typeof hold.body?.idempotency_key).toBe('string')
  expect((hold.body?.idempotency_key as string).length).toBeGreaterThan(8)
  await expect(cell()).toHaveAttribute('data-state', 'held')
  await expect(page.getByTestId('bookings-booking-info')).toContainText('Booking held for ACME')

  // Confirm.
  await page.getByTestId('bookings-confirm').click()
  await expect(page.getByTestId('bookings-notice')).toContainText('Booking confirmed for')
  expect(seen.filter((s) => s.method === 'POST' && s.path === '/booking/bookings/bk1/confirm')).toHaveLength(1)
  await expect(cell()).toHaveAttribute('data-state', 'booked')
  await expect(page.getByTestId('bookings-selected')).toHaveAttribute('data-state', 'booked')

  // Cancel with a reason; the fee the server recorded is shown.
  await page.getByTestId('bookings-cancel-btn').click()
  await expect(page.getByTestId('bookings-cancel-confirm')).toBeVisible()
  await page.getByTestId('bookings-reason').fill('Customer asked')
  await page.getByTestId('bookings-cancel-yes').click()
  await expect(page.getByTestId('bookings-notice')).toHaveText('Cancelled. Cancellation fee recorded: USD 25.00.')
  const cancel = seen.find((s) => s.method === 'POST' && s.path === '/booking/bookings/bk1/cancel')!
  expect(cancel.body).toEqual({ reason: 'Customer asked' })
  await expect(cell()).toHaveAttribute('data-state', 'cancelled')
  expect(seen.filter((s) => s.method === 'POST')).toHaveLength(3)

  const axe = await new AxeBuilder({ page }).analyze()
  expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`), 'axe on the bookings page').toEqual([])
  watch.assertNone()
})
