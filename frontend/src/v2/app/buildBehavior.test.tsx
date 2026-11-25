// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { entryKeys } from '../features/entry/api/entry'
import { App } from './App'
import { createAppRouter } from './router'

const project = '/projects/test-build'
const behavior = project + '/behavior/'
const custom = project + '/entities/Invoice/custom-fields'
const user = { id: 'user', name: 'Automation', email: 'tester@example.test', platform_role: 'customer', email_verified_at: '2026-11-23' }
const column = { id: 'title-field', name: 'title', type: 'string', required: true, unique: false }
const hook = {
  name: 'check_invoice', point: 'Invoice.validate', kind: 'pure', author: 'trusted',
  input: { name: 'CheckInvoiceInput', fields: [{ name: 'id', type: 'uuid' }] },
  output: { name: 'CheckInvoiceOutput', fields: [{ name: 'valid', type: 'bool' }] },
}
const wrapPage = (items: unknown[]) => ({ items, total: items.length })
const list = { entity: 'Invoice', enabled: true, max_keys: 50, max_bytes: 8192, items: [] as unknown[] }
const fixtureData: Record<string, unknown> = {
  [project]: { id: 'test-build', name: 'Training project', version: 7 },
  [project + '/status']: { ready: true, sections: [], issues: [], counts: {} },
  [project + '/spec']: { entities: [{ name: 'Invoice', fields: [column, { name: 'password', type: 'text' }] }], state_machines: [] },
  [project + '/entities']: wrapPage([{ id: 'invoice', name: 'Invoice', options: { operations: ['create'] } }]),
  [project + '/relations']: wrapPage([]),
  '/entities/invoice/fields': wrapPage([column]),
  [behavior + 'state-machines']: { state_machines: [] },
  [behavior + 'roles']: { roles: [{ name: 'staff', label: 'Staff' }] },
  [behavior + 'issues']: { issues: [] },
  [behavior + 'hooks']: { version: 7, hooks: [hook] },
  [behavior + 'events']: { version: 7, events: { enabled: true, adapter: 'in_process', retention_days: 14 } },
  [behavior + 'hook-effects']: { version: 7, hook_effects: { enabled: false, trusted_authors_only: false, webhook_hosts: [] } },
  [behavior + 'settings']: { version: 7, settings: [{ key: 'max_approvals', label: 'Maximum approvals', type: 'int', default: 10 }] },
  [behavior + 'sequences']: { version: 7, sequences: [{ name: 'ref', prefix: 'INV-', padding: 4, start: 2 }] },
  [behavior + 'lists']: { version: 7, lists: [] },
  [behavior + 'seed']: { version: 7, seed: [{ name: 'demo', seed: 42, as_of: '2026-01-01', tenants: 0, entities: [] }] },
  [custom]: list,
}

function renderScreen(section: string, { role = 'owner', request }: {
  role?: string; request?: (url: string, init?: RequestInit) => Response | undefined
} = {}) {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    const { pathname } = new URL(url)
    const override = request?.(pathname, init)
    if (override) return override
    if (pathname === project + '/members') return Response.json([{ user_id: user.id, role }])
    if (pathname === '/orgs') return Response.json(wrapPage([]))
    if (Object.hasOwn(fixtureData, pathname)) return Response.json(fixtureData[pathname])
    return Response.json({ code: 'not_found', details: [] }, { status: 404 })
  })
  vi.stubGlobal('fetch', fetcher)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(entryKeys.session(), user)
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [project + '/' + section] }))
  render(<App queryClient={queryClient} router={router} />)
  return { fetcher, router, queryClient }
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

it('hooks opens a deep-linked contract and points to its generated file in the editor', async () => {
  renderScreen('hooks?hook=check_invoice')
  const row = await screen.findByTestId('hook-row')
  expect(row.getAttribute('aria-current')).toBe('true')
  const editor = within(row).getByRole('link', { name: 'Open in editor' })
  expect(editor.getAttribute('href')).toContain('file=app%2Fcustom%2Fhooks%2Fcheck_invoice.py')
  fireEvent.click(within(row).getByRole('button', { name: 'Edit' }))
  expect(within(row).getByLabelText('Hook name')).toHaveProperty('value', 'check_invoice')
  expect(within(row).getByText('Output (fixed for this point)', { exact: false })).toBeTruthy()
})

it('hookeffects gates configuration on ownership and lists the requirements', async () => {
  renderScreen('hookeffects', { role: 'editor' })
  expect(await screen.findByText(/Only a project owner can change this/)).toBeTruthy()
  expect(await screen.findByLabelText('Trusted authors only')).toHaveProperty('disabled', true)
  expect(screen.getByText('A hook is declared')).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
})

it('events rejects out-of-range retention and saves valid changes with the observed version', async () => {
  const { fetcher } = renderScreen('events', { request: (path, init) => {
    if (path === behavior + 'events' && init?.method === 'PUT') return Response.json({
      version: 8, events: JSON.parse(String(init.body)).events,
    })
  } })
  const retention = await screen.findByLabelText('Retention days')
  expect(screen.getByText('invoice.updated')).toBeTruthy()
  expect(screen.queryByText(/Data fields.*password/)).toBeNull()
  fireEvent.change(retention, { target: { value: '4000' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(document.activeElement).toBe(retention)
  expect(fetcher.mock.calls.some(([, init]) => init?.method === 'PUT')).toBe(false)
  fireEvent.change(retention, { target: { value: '30' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByText('Saved (version 8).')).toBeTruthy()
  expect(JSON.parse(String(fetcher.mock.calls.find(([, init]) => init?.method === 'PUT')?.[1]?.body))).toEqual({
    expected_version: 7, events: { enabled: true, adapter: 'in_process', retention_days: 30 },
  })
})

it('settings keeps a dirty draft when switching to sequences and back', async () => {
  const { router } = renderScreen('settings')
  const defaultValue = await screen.findByLabelText('Default value')
  fireEvent.change(defaultValue, { target: { value: '20' } })
  fireEvent.mouseDown(screen.getByRole('tab', { name: 'Sequences' }), { button: 0, ctrlKey: false })
  expect(await screen.findByText('INV-0002')).toBeTruthy()
  await waitFor(() => expect(router.state.location.search.tab).toBe('sequences'))
  fireEvent.mouseDown(screen.getByRole('tab', { name: 'Settings' }), { button: 0, ctrlKey: false })
  await waitFor(() => expect(router.state.location.search.tab).toBe('settings'))
  expect(screen.getByLabelText('Default value')).toHaveProperty('value', '20')
})

it('seed edits a profile with a fixed seed and exposes the reset-only command', async () => {
  renderScreen('seed')
  const row = await screen.findByTestId('seed-row')
  expect(within(row).getByText('python -m app.seed --profile demo --reset-only')).toBeTruthy()
  fireEvent.click(within(row).getByRole('button', { name: 'Edit' }))
  expect(within(row).getByLabelText('Seed number')).toHaveProperty('value', '42')
  expect(within(row).getByText(/Total rows for this profile: 0/)).toBeTruthy()
  expect(within(row).getByLabelText('Add an entity to seed')).toBeTruthy()
})

it('customfields defines a constrained field using the entity endpoint', async () => {
  const { fetcher } = renderScreen('customfields', { request: (path, init) => {
    if (path === custom && init?.method === 'POST') return Response.json(JSON.parse(String(init.body)), { status: 201 })
  } })
  fireEvent.click(await screen.findByRole('button', { name: 'Add a field' }))
  const name = await screen.findByLabelText('Field name')
  fireEvent.change(name, { target: { value: 'reference_code' } })
  fireEvent.change(screen.getByLabelText('Longest text'), { target: { value: '63' } })
  fireEvent.change(screen.getByLabelText('Allowed values'), { target: { value: 'AA\nBB' } })
  fireEvent.click(screen.getByRole('button', { name: 'Add field' }))
  expect(await screen.findByText('Custom fields updated.')).toBeTruthy()
  const submitted = fetcher.mock.calls.find(([, init]) => init?.method === 'POST')
  expect(submitted?.[0]).toMatch(/\/entities\/Invoice\/custom-fields$/)
  expect(JSON.parse(String(submitted?.[1]?.body))).toEqual({
    name: 'reference_code', type: 'string', required: false, max_length: 63, enum_values: ['AA', 'BB'],
  })
})
