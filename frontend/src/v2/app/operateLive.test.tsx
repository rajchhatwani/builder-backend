// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { members, projectId, root, user } from '../../../e2e/v2/fixtures/connect-a'
import { preview, previewId, previewPath } from '../../../e2e/v2/fixtures/connect-b'
import { bookingReference, normalTables, ownerPacks, runtimeData, titles } from '../../../e2e/v2/fixtures/operate-b'
import type { Screen } from '../../../e2e/v2/fixtures/operate-b'
import { entryKeys } from '../features/entry/api/entry'
import { App } from './App'
import { createAppRouter } from './router'

vi.mock('../features/guided/components/PreviewCredentials', async importOriginal => ({
  ...await importOriginal<typeof import('../features/guided/components/PreviewCredentials')>(),
  usePreviewCredentials: () => ({ credentials: { [previewId]: { token: 'preview-token', bearer: 'runtime-user', revision: 1 } }, dispatch: vi.fn() }),
}))
const data: Record<string, unknown> = {
  '/orgs': { items: [], total: 0 },
  [root]: { id: projectId, name: 'Operations workspace', version: 3 },
  [root + '/status']: { ready: true, sections: [], counts: {}, issues: [] },
  [root + '/members']: members,
  [root + '/previews']: [preview],
  [root + '/workspaces']: [],
  [root + '/behavior/packs']: ownerPacks,
}
function open(path: string, override?: (url: URL, init?: RequestInit) => Response | undefined) {
  const fetcher = vi.fn(async (value: string, init?: RequestInit) => {
    const url = new URL(value)
    const response = override?.(url, init)
    if (response) return response
    if (url.pathname.startsWith(previewPath + '/')) {
      expect(init?.headers).toMatchObject({ Authorization: 'Bearer runtime-user', 'X-Preview-Token': 'preview-token' })
      expect(init?.credentials).toBe('omit')
      const payload = runtimeData(url.pathname.slice(previewPath.length))
      if (payload !== undefined) return Response.json(payload)
    }
    return Object.hasOwn(data, url.pathname) ? Response.json(data[url.pathname]) :
      Response.json({ code: 'not_found', details: [] }, { status: 404 })
  })
  vi.stubGlobal('fetch', fetcher)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(entryKeys.session(), user)
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [root + '/' + path] }))
  render(<App queryClient={queryClient} router={router} />)
  return { fetcher, router }
}
beforeEach(() => {
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  localStorage.setItem('v2-language', 'en')
})
afterEach(() => {
  cleanup()
  localStorage.clear()
  vi.unstubAllGlobals()
})

for (const name of Object.keys(titles) as Screen[]) {
  it(name + ' renders preview data in the project route', async () => {
    open(name + (name === 'bookings' ? '?week=2026-01-05' : ''))
    const [title, content] = titles[name]
    expect(await screen.findByRole('heading', { level: 1, name: title }, { timeout: 5000 })).toBeTruthy()
    const table = await screen.findByRole('table', { name: normalTables[name] })
    expect(within(table).getByRole('cell', { name: name === 'bookings' ? bookingReference : content })).toBeTruthy()
    if (name === 'map') expect(screen.getByRole('button', { name: 'co: Select courier-17' })).toBeTruthy()
  })
}
it('recovers the accounts list and opens the transaction reversal dialog', async () => {
  let failing = true
  open('ledger', url => failing && url.pathname === previewPath + '/ledger/accounts'
    ? Response.json({ code: 'unavailable', details: [] }, { status: 503 }) : undefined)
  const retry = await screen.findByRole('button', { name: 'Try again' })
  failing = false
  fireEvent.click(retry)
  const accounts = await screen.findByRole('table', { name: 'Accounts' })
  expect(within(accounts).getByRole('cell', { name: 'Cash on hand' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Show entries' }))
  expect(await screen.findByRole('table', { name: 'Entries' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Reverse' }))
  expect(screen.getByRole('dialog', { name: 'Reverse' })).toBeTruthy()
})
it('keeps an exact ledger amount past the JavaScript safe integer ceiling', async () => {
  open('ledger', url => url.pathname === previewPath + '/ledger/balances' ? new Response(
    '{"items":[{"account_id":"cash","code":"1000","name":"Precision account","currency":"USD","exponent":2,"balance_minor":90071992547409939,"debit_total_minor":0,"credit_total_minor":0}],"totals":[]}',
  ) : undefined)
  const balances = await screen.findByRole('table', { name: 'Balances' })
  expect(within(balances).getByRole('cell', { name: 'USD 900,719,925,474,099.39' })).toBeTruthy()
})
it('passes the original packs version and preserves the draft on conflict', async () => {
  const { fetcher } = open('bookingadmin', (url, init) => url.pathname === root + '/behavior/packs' && init?.method === 'PUT' ?
    Response.json({ code: 'conflict', message: 'A newer version exists.', details: [] }, { status: 409 }) : undefined)
  const hold = await screen.findByLabelText('Hold time (seconds)')
  await waitFor(() => expect(hold).toHaveProperty('disabled', false))
  fireEvent.change(hold, { target: { value: '900' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save rules' }))
  expect(await screen.findByText('A newer version exists.')).toBeTruthy()
  expect(hold).toHaveProperty('value', '900')
  const write = fetcher.mock.calls.find(([, init]) => init?.method === 'PUT')
  expect(JSON.parse(String(write?.[1]?.body))).toMatchObject({ expected_version: 3, packs: { booking: {
    hold_ttl_seconds: 900, cancellation: { fee_minor: 2500 },
  } } })
})
