// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { entryKeys } from '../features/entry/api/entry'
import { App } from './App'
import { createAppRouter } from './router'

vi.mock('../features/diagrams/components/DiagramCanvas', () => ({ default: () => null }))

const project = '/projects/test-diagrams'
const user = { id: 'user', name: 'Automation', email: 'tester@example.test', platform_role: 'customer', email_verified_at: '2026-11-23' }
const spec = {
  project: { name: 'Training project' },
  entities: [{ name: 'Invoice', table_name: 'invoices', fields: [{ name: 'total', type: 'decimal' }] }],
  auth: { enabled: true, roles: [{ name: 'billing', label: 'Billing' }] },
}

function open({ search = '', role = 'owner', read = () => Response.json(spec), extra = {} }: {
  search?: string; role?: string; read?: () => Response; extra?: Record<string, () => Response>
} = {}) {
  const request = vi.fn(async (url: string) => {
    const { pathname } = new URL(url)
    if (pathname === project) return Response.json({ id: 'test-diagrams', name: 'Training project' })
    if (pathname === project + '/status') return Response.json({ ready: true, sections: [], issues: [], counts: {} })
    if (pathname === project + '/members') return Response.json([{ user_id: user.id, role }])
    if (pathname === project + '/spec') return read()
    if (Object.hasOwn(extra, pathname)) return extra[pathname]()
    if (pathname === project + '/access/matrix') return Response.json({
      roles: ['billing'], entities: ['Invoice'], cells: [{ role: 'billing', entity: 'Invoice', layer: 'object', target: 'get', value: 'yes' }],
    })
    return Response.json({ items: [], total: 0 })
  })
  vi.stubGlobal('fetch', request)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(entryKeys.session(), user)
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [project + '/diagrams' + search] }))
  render(<App queryClient={queryClient} router={router} />)
  return { router, request }
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

it('shows saved relationships and makes the catalogue selection bookmarkable', async () => {
  const { router } = open({ role: 'viewer' })
  expect(await screen.findByRole('heading', { name: 'Entity-relationship' }, { timeout: 3000 })).toBeTruthy()
  expect(await screen.findByText('Read-only view of the saved project.')).toBeTruthy()
  expect(within(screen.getByRole('table', { name: 'Fields' })).getByText('decimal')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: /Access matrix heat-map/ }))
  await waitFor(() => expect(router.state.location.search.view).toBe('D13'))
  expect(await screen.findByRole('columnheader', { name: 'billing' })).toBeTruthy()
  expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Access matrix heat-map' }))
})

it('preserves the error until retry and shows the empty action after recovery', async () => {
  let response = Response.json({ code: 'unavailable', message: 'Service unavailable' }, { status: 503 })
  open({ read: () => response })
  expect(await screen.findByText('We could not load your diagrams')).toBeTruthy()
  response = Response.json({ project: spec.project, entities: [] })
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  expect(await screen.findByRole('link', { name: 'Open the data model' })).toHaveProperty('href', expect.stringContaining('/model'))
})

it('uses the saved generation manifest and opens its selected path in the code editor', async () => {
  open({ search: '?view=D03', extra: {
    [project + '/generations']: () => Response.json({ items: [{ id: 'generation-1' }], total: 1 }),
    '/generations/generation-1': () => Response.json({ file_manifest: [{ path: 'app/billing/router.py', size: 40 }] }),
  } })
  expect(await screen.findByRole('link', { name: 'Open app/billing/router.py in the editor' }, { timeout: 3000 }))
    .toHaveProperty('href', expect.stringContaining('/code?file=app%2Fbilling%2Frouter.py'))
})

it('compares against the before-first snapshot and reports a server conflict', async () => {
  const { request } = open({ search: '?view=D41', extra: {
    [project + '/spec/ops']: () => Response.json({ items: [{ seq: 25, op_type: 'add_entity', actor: { kind: 'user' } }], total: 1 }),
    [project + '/spec/at/0']: () => Response.json({ code: 'spec_changed', message: 'Changed outside the op log', details: [] }, { status: 409 }),
  } })
  expect(await screen.findByText('The diagram source changed. Reload the saved spec.')).toBeTruthy()
  expect(request.mock.calls.some(([url]) => url.endsWith('/spec/at/0'))).toBe(true)
})
