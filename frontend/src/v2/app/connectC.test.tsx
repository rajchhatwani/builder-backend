// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { members, projectId, root, user } from '../../../e2e/v2/fixtures/connect-a'
import { packRoles, packs, packsReply, packScreens, packSpec } from '../../../e2e/v2/fixtures/connect-c'
import { entryKeys } from '../features/entry/api/entry'
import { App } from './App'
import { createAppRouter } from './router'

const path = root + '/behavior/packs'
type Write = { packs: typeof packs; expected_version: number }
function open(section: string, respond?: (method: string, body: Write) => Response | undefined, fixture: unknown = packs) {
  let current = structuredClone(fixture)
  let version = 3
  const writes: Write[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
    const { pathname } = new URL(url, window.location.origin)
    if (pathname === '/account/me') return Response.json(user)
    if (pathname === '/orgs') return Response.json({ items: [], total: 0 })
    if (pathname === root) return Response.json({ id: projectId, name: 'People Directory', slug: 'directory', version: 1 })
    if (pathname === root + '/status') return Response.json({ ready: true, sections: [], issues: [], counts: {} })
    if (pathname === root + '/members') return Response.json(members)
    if (pathname === root + '/workspaces' || pathname === root + '/previews') return Response.json([])
    if (pathname === root + '/spec') return Response.json(packSpec)
    if (pathname === root + '/behavior/roles') return Response.json({ roles: packRoles })
    if (pathname === root + '/behavior/issues') return Response.json({ issues: [] })
    if (pathname === path) {
      if (options?.method !== 'PUT') return Response.json(packsReply(current, version))
      const body = JSON.parse(String(options.body)) as Write
      writes.push(body)
      const response = respond?.('PUT', body)
      if (response) return response
      current = body.packs
      return Response.json(packsReply(current, ++version))
    }
    return Response.json({ code: 'not_found', details: [] }, { status: 404 })
  }))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(entryKeys.session(), user)
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [root + '/' + section] }))
  render(<App router={router} queryClient={queryClient} />)
  return writes
}

beforeEach(() => {
  localStorage.setItem('v2-language', 'en')
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})
afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals() })

async function mainFor(id: keyof typeof packScreens) {
  const main = within(await screen.findByRole('main'))
  await main.findByRole('heading', { name: packScreens[id].title }, { timeout: 5000 })
  await waitFor(() => expect(main.getByTestId('switch-off').querySelector('button')).toHaveProperty('disabled', false))
  return main
}

const numeric = [
  ['ledgersettings', 'Max entries', '250', 'money', 'ledger', 'max_entries'],
  ['reconsettings', 'Tolerance minor', '10', 'money', 'reconciliation', 'tolerance_minor'],
  ['bookingsettings', 'Hold ttl seconds', '900', 'booking', null, 'hold_ttl_seconds'],
  ['geosettings', 'Max places', '200000', 'operations', 'geo', 'max_places'],
  ['locationsettings', 'Max subjects', '200000', 'operations', 'location', 'max_subjects'],
] as const

it.each(numeric)('%s saves a field through the shared versioned endpoint', async (id, label, value, pack, block, field) => {
  const writes = open(id)
  const main = await mainFor(id)
  fireEvent.change(main.getByRole('spinbutton', { name: label }), { target: { value } })
  fireEvent.click(main.getByRole('button', { name: /^Save$/ }))
  await waitFor(() => expect(main.getByTestId('save-note').textContent).toBe('Saved (version 4).'))
  expect(writes).toMatchObject([{ expected_version: 3, packs: {
    ai: packs.ai, [pack]: block ? { [block]: { [field]: Number(value) } } : { [field]: Number(value) },
  } }])
})

it('currency settings saves lowercase tax rates with currency and rounding intact', async () => {
  const writes = open('currencysettings')
  const main = await mainFor('currencysettings')
  fireEvent.change(main.getByRole('textbox', { name: 'Rates bp' }), { target: { value: '{"vat": 1700}' } })
  fireEvent.click(main.getByRole('button', { name: /^Save$/ }))
  await waitFor(() => expect(main.getByTestId('save-note').textContent).toBe('Saved (version 4).'))
  expect(writes).toMatchObject([{ expected_version: 3, packs: { money: {
    currency: { currencies: ['USD', 'JPY'], rounding: 'half_even', tax: { rates_bp: { vat: 1700 } } },
  } } }])
})

it('invoicing initializes payouts and maps a 422 to its nested account field', async () => {
  const writes = open('invoicingsettings', () => Response.json({
    code: 'invalid_spec', message: 'Invalid spec',
    details: [{ loc: ['body', 'packs', 'money', 'invoicing', 'payouts', 'commission_account'], msg: 'Account rejected.' }],
  }, { status: 422 }))
  const main = await mainFor('invoicingsettings')
  fireEvent.click(main.getByRole('checkbox', { name: 'Enable Payouts' }))
  expect(main.getByRole('spinbutton', { name: 'Commission bp' })).toHaveProperty('value', '1000')
  fireEvent.click(main.getByRole('button', { name: /^Save$/ }))
  expect(await main.findByText('Account rejected.')).toBeTruthy()
  expect(writes).toMatchObject([{ expected_version: 3, packs: { money: {
    invoicing: { payouts: { commission_bp: 1000, seller_payable_account: 'seller_payable', commission_account: 'commission' } },
  } } }])
})

it('switches on reconciliation with defaults while preserving currency and unrelated packs', async () => {
  const writes = open('reconsettings', undefined, { ...packs, money: { ...packs.money, reconciliation: null } })
  const activate = await screen.findByRole('button', { name: 'Switch on reconciliation settings' }, { timeout: 5000 })
  await waitFor(() => expect(activate).toHaveProperty('disabled', false))
  fireEvent.click(activate)
  const main = await mainFor('reconsettings')
  await waitFor(() => expect(main.getByTestId('save-note').textContent).toBe('Saved (version 4).'))
  expect(writes).toEqual([{ expected_version: 3, packs: { ...packs, money: { ...packs.money,
    reconciliation: { read_roles: ['admin'], run_roles: ['admin'], tolerance_minor: 0, max_lines: 1000 },
  } } }])
})

it('keeps a booking window edit and confirms widening manager route access', async () => {
  const writes = open('bookingsettings?bookingKind=0')
  const main = await mainFor('bookingsettings')
  const end = main.getByLabelText('Window 1 end')
  fireEvent.change(end, { target: { value: '16:00' } })
  const managers = within(main.getByRole('group', { name: 'Manage roles' }))
  fireEvent.click(await managers.findByRole('checkbox', { name: 'Administrator' }))
  fireEvent.click(main.getByRole('button', { name: /^Save$/ }))
  const dialog = within(await screen.findByRole('dialog'))
  expect(dialog.getByText('Any signed-in user could call manager routes. Nobody would have manager status for booking visibility.')).toBeTruthy()
  expect(writes).toHaveLength(0)
  fireEvent.click(dialog.getByRole('button', { name: /^Save$/ }))
  await waitFor(() => expect(main.getByTestId('save-note').textContent).toBe('Saved (version 4).'))
  expect(writes).toMatchObject([{ expected_version: 3, packs: { booking: {
    manage_roles: [], kinds: [{ schedule: { mon: [{ start: '09:00', end: '16:00' }] } }, {}],
  } } }])
})
