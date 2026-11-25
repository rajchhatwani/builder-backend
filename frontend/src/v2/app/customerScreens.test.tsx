// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { App } from './App'
import { createAppRouter } from './router'
import { entryKeys } from '../features/entry/api/entry'
import type { UserAccount } from '../features/entry/api/entry'

const user: UserAccount = {
  id: 'fixture-user', email: 'tester@example.test', name: 'Test Builder', status: 'active', platform_role: 'customer',
  email_verified_at: '2026-11-23T12:00:00Z', must_change_password: false, created_at: '2026-11-23T12:00:00Z', last_login_at: null,
}

const page = (items: unknown[] = []) => Response.json({ items, total: items.length, limit: 200, offset: 0 })
const missing = () => Response.json({ code: 'missing', details: [] }, { status: 404 })
function fixture(path: string, respond: (path: string) => Response) {
  const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
    const path = new URL(url).pathname
    return path === '/orgs' || path === '/orgs/invitations/pending' ? page() : respond(path)
  })
  vi.stubGlobal('fetch', fetchMock)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(entryKeys.session(), user)
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
  return fetchMock
}

beforeEach(() => {
  localStorage.setItem('v2-language', 'en')
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})
afterEach(() => {
  cleanup()
  localStorage.clear()
  vi.unstubAllGlobals()
})

it('shows the create action after a projects retry succeeds', async () => {
  let offline = true
  fixture('/projects', path => path === '/projects'
    ? offline ? Response.json({ code: 'offline', details: [] }, { status: 503 }) : page()
    : missing())
  const retry = await screen.findByRole('button', { name: 'Try again' })
  offline = false
  fireEvent.click(retry)
  expect((await screen.findByRole('link', { name: 'Create a project' })).getAttribute('href')).toBe('/projects/new')
})

it('keeps a locked project out of project-detail and membership requests', async () => {
  const fetchMock = fixture('/projects', path => path === '/projects' ? page([{
    id: 'locked', name: 'Locked example', slug: 'locked-example', organization_locked: true,
  }]) : missing())
  expect(await screen.findByRole('heading', { name: 'Locked example' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Delete' })).toBeNull()
  expect(fetchMock.mock.calls.some(([url]) => url.includes('/projects/locked/'))).toBe(false)
})

it('validates the new project name and slug before requesting a create', async () => {
  const fetchMock = fixture('/projects/new', missing)
  const name = await screen.findByRole('textbox', { name: 'Project name' })
  const slug = screen.getByRole('textbox', { name: 'Slug (optional)' })
  fireEvent.change(slug, { target: { value: '123-Invalid' } })
  fireEvent.click(screen.getByRole('button', { name: 'Create project' }))
  expect(document.activeElement).toBe(name)
  expect(screen.getByText('Use lowercase letters, digits and hyphens, starting with a letter.')).toBeTruthy()
  expect(fetchMock.mock.calls.some(([url, init]) => url.endsWith('/projects') && init?.method === 'POST')).toBe(false)
})

it('asks for password confirmation and shows a distinct empty token state', async () => {
  const fetchMock = fixture('/account', path => {
    if (path === '/projects') return page()
    if (path === '/account/tokens') return Response.json([])
    if (path === '/account/mfa') return Response.json({ totp_enabled: false, required_by: [], sso_only: false })
    return missing()
  })
  expect(await screen.findByText('No active tokens.')).toBeTruthy()
  fireEvent.change(screen.getByLabelText('Current password'), { target: { value: 'old-password' } })
  fireEvent.change(screen.getByLabelText('New password', { exact: true }), { target: { value: 'coral-winter-lake' } })
  fireEvent.change(screen.getByLabelText('Repeat new password'), { target: { value: 'mistyped' } })
  fireEvent.click(screen.getByRole('button', { name: 'Change password' }))
  expect(await screen.findByText('The two new passwords are different.')).toBeTruthy()
  expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/account/password'))).toBe(false)
})

it('preserves account history as the return destination during anonymous redirects', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({}, { status: 401 })))
  const queryClient = new QueryClient()
  queryClient.setQueryData(entryKeys.session(), null)
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: ['/account?history=true'] }))
  render(<App queryClient={queryClient} router={router} />)
  expect(await screen.findByLabelText('Email')).toBeTruthy()
  expect(router.state.location.search).toMatchObject({ next: '/account?history=true' })
})
