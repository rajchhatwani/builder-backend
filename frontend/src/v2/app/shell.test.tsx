// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { App } from './App'
import { createAppRouter } from './router'

const id = 'inventory'
const root = '/projects/' + id
const auth = { id: 'consider_auth', title: 'Decide how people sign in', reason: 'Your API has no user accounts yet.', section: 'auth' }
const generate = { id: 'generate', title: 'Generate your backend', reason: 'The model is valid.', section: 'generate' }

function setup(role: string, memberError = false) {
  let dismissed = false
  const fetch = vi.fn(async (address: string, init?: RequestInit) => {
    const path = new URL(address).pathname
    if (path === '/account/refresh') return Response.json({ access_token: 'fixture' })
    if (path === '/account/me') return Response.json({ id: 'me', platform_role: 'customer', email_verified_at: '2026-01-01' })
    if (path === root) return Response.json({ id, name: 'Inventory', version: 3 })
    if (path === root + '/members') {
      if (memberError) {
        memberError = false
        return Response.json({ code: 'fixture' }, { status: 500 })
      }
      return Response.json([{ user_id: 'me', name: 'Mina Chen', email: 'mina@example.test', role }])
    }
    if (path === root + '/roles' || path === root + '/generations') return Response.json({ items: [], total: 0 })
    if (path.startsWith(root + '/status')) {
      if (init?.method === 'POST') dismissed = true
      if (init?.method === 'DELETE') dismissed = false
      return Response.json({
        ready: true, issues: [], counts: { entities: 1 },
        sections: [{ id: 'model', label: 'Data model', configured: true, issue_count: 0 }],
        next_step: dismissed ? generate : auth, dismissed_steps: dismissed ? [{ ...auth, dismissed: true }] : [],
      })
    }
    return Response.json({}, { status: 404 })
  })
  vi.stubGlobal('fetch', fetch)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [root + '/overview'] }))
  render(<App queryClient={queryClient} router={router} />)
  return { fetch, router }
}

beforeEach(() => {
  localStorage.setItem('v2-language', 'en')
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('renders Overview and dismisses and restores the same server-side suggestion', async () => {
  const { fetch } = setup('editor')
  expect(await screen.findByRole('heading', { name: 'Home' })).toBeTruthy()
  expect(await screen.findByRole('heading', { name: 'Setup checklist' })).toBeTruthy()
  fireEvent.click(await screen.findByRole('button', { name: 'Not now' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Show again' }))
  expect(await screen.findByRole('button', { name: 'Not now' })).toBeTruthy()
  expect(fetch.mock.calls.filter(([path]) => path.includes('/status/dismiss')).map(([, init]) => init?.method)).toEqual(['POST', 'DELETE'])
})

it('gates Overview writes for a viewer', async () => {
  setup('viewer')
  expect(await screen.findByText('Only project editors and owners can dismiss or restore steps.')).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Not now' })).toBeNull()
})

it('preserves a failed membership read until Share explicitly retries', async () => {
  const { fetch } = setup('viewer', true)
  await screen.findByText('Could not load project permissions.')
  fireEvent.click(screen.getByRole('button', { name: 'Share' }))
  const share = await screen.findByRole('dialog', { name: 'People with access to Inventory' })
  expect(await within(share).findByText("Can't load the members.")).toBeTruthy()
  const memberCalls = () => fetch.mock.calls.filter(([path]) => path.endsWith('/members'))
  expect(memberCalls()).toHaveLength(1)
  fireEvent.click(within(share).getByRole('button', { name: 'Retry' }))
  expect(await within(share).findByText('Mina Chen (you)')).toBeTruthy()
  expect(memberCalls()).toHaveLength(2)
})

it('filters shell commands, navigates with the keyboard, and keeps sharing read-only', async () => {
  const { router } = setup('viewer')
  expect(await screen.findByText('Inventory', { selector: '[data-testid=shell-project]' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Share' }))
  const share = await screen.findByRole('dialog', { name: 'People with access to Inventory' })
  expect(await within(share).findByText('Only owners can change who has access.')).toBeTruthy()
  fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
  expect(screen.queryByRole('combobox', { name: 'Search commands' })).toBeNull()
  fireEvent.click(within(share).getByRole('button', { name: 'Done' }))
  fireEvent.keyDown(window, { key: 'k', metaKey: true })
  const search = await screen.findByRole('combobox', { name: 'Search commands' })
  fireEvent.change(search, { target: { value: 'model data' } })
  expect(screen.getAllByRole('option')).toHaveLength(1)
  fireEvent.keyDown(search, { key: 'ArrowDown' })
  fireEvent.keyDown(search, { key: 'Enter' })
  await waitFor(() => expect(router.state.location.pathname).toBe(root + '/model'))
  expect(screen.queryByRole('combobox', { name: 'Search commands' })).toBeNull()
})
