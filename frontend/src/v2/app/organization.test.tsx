// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { App } from './App'
import { createAppRouter } from './router'
import { normalizeEntryAddress } from './entryCompatibility'
import { entryKeys } from '../features/entry/api/entry'

const slug = 'library'
const path = '/org/library'
const prefix = '/orgs/library'
const user = { id: 'reader', name: 'Library Reader', email: 'reader@example.test', email_verified_at: '2026-11-22', default_organization_id: 'library' }
const org = { id: 'library', slug, name: 'City Library', kind: 'team', member_count: 1 }
const person = { user_id: 'owner', name: 'Library Owner', email: 'owner@example.test', role: 'owner', joined_at: '2026-11-22' }

const respond = (data: unknown, code = 200) => Response.json(data, { status: code })
function show(surface = path, { role = 'owner', locked = false, mfa = false, membersUnavailable = false } = {}) {
  let requireMfa = false
  const fetch = vi.fn(async (url: string, request?: RequestInit) => {
    const { pathname } = new URL(url)
    if (pathname === prefix) return respond({ ...org, my_role: role, deletion_scheduled_for: locked ? '2026-11-25' : null })
    if (pathname === prefix + '/members') {
      if (mfa) return respond({ code: 'org_mfa_required' }, 403)
      if (membersUnavailable) {
        membersUnavailable = false
        return respond({ code: 'fixture_unavailable' }, 503)
      }
      return respond({ items: [person] })
    }
    if (pathname === prefix + '/plan') return respond({
      plan: { display_name: 'Team', id: 'team' }, usage: {}, subscription: { status: 'active' }, upgrades: [],
    })
    if (pathname === prefix + '/policies') {
      if (request?.method === 'PATCH') requireMfa = Boolean(JSON.parse(String(request.body)).require_mfa)
      return respond({ require_mfa: requireMfa, session_ttl_hours: null, allow_impersonation: true, default_session_hours: 168, members_without_mfa: 1 })
    }
    if (pathname === prefix + '/usage') return respond({ metrics: [{ metric: 'builds', unit: 'calls', period: 'month', used: 4, limit: 10, refused: 0 }] })
    return respond({ items: [] })
  })
  vi.stubGlobal('fetch', fetch)
  const client = new QueryClient()
  client.setQueryData(entryKeys.session(), user)
  const router = createAppRouter(client, createMemoryHistory({ initialEntries: [surface] }))
  render(<App queryClient={client} router={router} />)
  return { fetch, router }
}

beforeEach(() => {
  localStorage.setItem('v2-language', 'en')
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})
afterEach(() => {
  cleanup()
  history.replaceState(null, '', '/')
  vi.unstubAllGlobals()
})

it('renders owner role controls and puts the selected tab in the URL', async () => {
  const { router } = show()
  expect(await screen.findByRole('heading', { name: 'City Library' })).toBeTruthy()
  expect(await screen.findByRole('combobox', { name: 'Role of owner@example.test' })).toBeTruthy()
  fireEvent.mouseDown(screen.getByRole('tab', { name: 'Usage' }), { button: 0, ctrlKey: false })
  await waitFor(() => expect(router.state.location.search).toMatchObject({ tab: 'usage' }))
  expect(await screen.findByTestId('usage-edit')).toBeTruthy()
})

it('protects admin tabs and lets a member see usage without editing', async () => {
  const { fetch } = show(path + '?tab=ai', { role: 'member' })
  expect(await screen.findByTestId('ai-noaccess')).toBeTruthy()
  fireEvent.mouseDown(screen.getByRole('tab', { name: 'Usage' }), { button: 0, ctrlKey: false })
  expect((await screen.findByTestId('usage-used')).textContent).toBe('4')
  expect(screen.queryByTestId('usage-edit')).toBeNull()
  expect(fetch.mock.calls.some(([url]) => url.includes('/ai/'))).toBe(false)
})

it('recovers the People tab when Retry follows a failed member request', async () => {
  const { fetch } = show(path, { membersUnavailable: true })
  const retry = await screen.findByRole('button', { name: 'Retry' })
  expect(fetch.mock.calls.some(([url]) => url.endsWith('/plan'))).toBe(false)
  fireEvent.click(retry)
  expect(await screen.findByRole('combobox', { name: 'Role of owner@example.test' })).toBeTruthy()
  expect(fetch.mock.calls.filter(([url]) => url.endsWith('/members'))).toHaveLength(2)
})

it('reads only the organization while deletion is pending and exposes owner recovery', async () => {
  const { fetch } = show(path, { locked: true })
  expect(await screen.findByRole('button', { name: 'Cancel deletion' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Download export' })).toBeTruthy()
  expect(screen.queryByRole('tablist')).toBeNull()
  expect(fetch.mock.calls.filter(([url]) => new URL(url).pathname.startsWith(prefix)).map(([url]) => new URL(url).pathname)).toEqual([prefix])
})

it('routes an MFA-blocked session to its recovery options without opening the plan', async () => {
  const { fetch } = show(path + '?tab=plan', { mfa: true })
  expect(await screen.findByRole('link', { name: 'Open your account' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Leave' })).toBeTruthy()
  expect(fetch.mock.calls.some(([url]) => url.endsWith('/plan'))).toBe(false)
})

it('requires confirmation before enforcing two-factor and sends only the changed policy', async () => {
  const { fetch } = show(path + '?tab=security')
  const mfa = await screen.findByRole('checkbox', { name: /Require two-factor for every member/ })
  fireEvent.click(mfa)
  fireEvent.click(screen.getByRole('button', { name: 'Save policies' }))
  expect(fetch.mock.calls.some(([, request]) => request?.method === 'PATCH')).toBe(false)
  const dialog = await screen.findByRole('dialog')
  const confirm = Array.from(dialog.querySelectorAll('button')).find(button => button.textContent === 'Save policies')
  expect(confirm).toBeDefined()
  fireEvent.click(confirm!)
  await waitFor(() => expect(fetch.mock.calls.find(([, request]) => request?.method === 'PATCH')?.[1]?.body)
    .toBe(JSON.stringify({ require_mfa: true })))
})

it('normalizes backend billing and SSO returns into the path router', () => {
  history.replaceState(null, '', '/#/org/library/plan?checkout=success')
  normalizeEntryAddress()
  expect(location.pathname + location.search + location.hash).toBe(path + '?checkout=success&tab=plan')
  history.replaceState(null, '', '/#/org/library/sso?sso_test=ok')
  normalizeEntryAddress()
  expect(location.pathname + location.search + location.hash).toBe(path + '?sso_test=ok&tab=sso')
})
