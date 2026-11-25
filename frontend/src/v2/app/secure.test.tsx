// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { entryKeys } from '../features/entry/api/entry'
import { App } from './App'
import { createAppRouter } from './router'

const project = '/projects/secure-unit'
const user = { id: 'tester', name: 'Tester', email: 'tester@example.test', platform_role: 'customer', email_verified_at: '2026-01-01' }
const auth = {
  id: 'auth', enabled: true, provider: 'builtin', deletion_mode: 'soft', token_store: 'db', jwt_algorithm: 'HS256',
  access_token_ttl_minutes: 15, refresh_token_ttl_days: 7, otp_ttl_minutes: 10, email_verification_required: false,
  email_magic_link_enabled: false, sms_otp_enabled: false, security_headers_enabled: true, login_rate_limit: '5/15minutes',
  register_rate_limit: '10/hour', reset_rate_limit: '3/hour', suite: null,
}
const keycloak = {
  id: 'keycloak', mode: 'own', active: false, realm: 'directory', api_client_id: 'directory-api', web_client_id: 'directory-web',
  password_min_length: 12, mfa: 'optional', session_idle_minutes: 30, session_max_hours: 10, audit_retention_days: 90,
  redirect_uris: [], identity_providers: [], source_project_id: null,
}
type Handler = (path: string, method: string, body: unknown) => Response | undefined

function open(section: string, handle: Handler, role = 'owner') {
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    const { pathname } = new URL(url)
    const body: unknown = typeof options?.body === 'string' ? JSON.parse(options.body) : undefined
    const method = options?.method ?? 'GET'
    const override = handle(pathname, method, body)
    if (override) return override
    if (pathname === project) return Response.json({ id: 'secure-unit', name: 'Directory', slug: 'directory' })
    if (pathname === project + '/members') return Response.json([{ user_id: user.id, role }])
    if (pathname === project + '/status') return Response.json({ ready: true, sections: [], issues: [], counts: {} })
    if (pathname === project + '/auth') return Response.json(auth)
    if (pathname === project + '/keycloak') return Response.json(keycloak)
    if (pathname === project + '/validate') return Response.json({ valid: true, issues: [] })
    return Response.json({ code: 'not_found', details: [] }, { status: 404 })
  })
  vi.stubGlobal('fetch', fetcher)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(entryKeys.session(), user)
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [project + '/' + section] }))
  render(<App queryClient={queryClient} router={router} />)
  return { router, fetcher }
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

it('confirms the authentication access-widening response before sending an override', async () => {
  const writes: unknown[] = []
  open('auth', (path, method, body) => {
    if (path !== project + '/auth' || method !== 'PATCH') return
    writes.push(body)
    return writes.length === 1 ? Response.json({ code: 'access_weakened', details: [] }, { status: 409 })
      : Response.json({ ...auth, enabled: false })
  })
  await screen.findByRole('heading', { name: 'Authentication' })
  const enabled = await screen.findByRole('checkbox', { name: 'Auth enabled' })
  await waitFor(() => expect((enabled as HTMLInputElement).disabled).toBe(false))
  fireEvent.click(enabled)
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByRole('dialog', { name: 'This makes some rules public' })).toBeTruthy()
  expect(writes).toEqual([expect.objectContaining({ enabled: false })])
  fireEvent.click(screen.getByRole('button', { name: 'Save anyway' }))
  await waitFor(() => expect(writes.at(1)).toEqual(expect.objectContaining({ enabled: false, confirm_weakening: true })))
})

it('checks the Keycloak switch impact and prevents switching when there is a blocker', async () => {
  const { fetcher } = open('keycloak', path => path === project + '/keycloak/impact' ? Response.json({
    action: 'enable', provider: 'builtin', can_proceed: false, blockers: ['Add a redirect URL.'], warnings: [], dependents: [],
  }) : undefined)
  fireEvent.click(await screen.findByRole('button', { name: 'Turn on…' }))
  expect(await screen.findByText('Add a redirect URL.')).toBeTruthy()
  expect((screen.getByRole('button', { name: 'Turn on Keycloak' }) as HTMLButtonElement).disabled).toBe(true)
  expect(fetcher.mock.calls.some(([url, init]) => url.endsWith('/keycloak/enable') && init?.method === 'POST')).toBe(false)
})

it('preserves a saved migration during membership edits and retries only the second write', async () => {
  const migration = { state: 'legacy_read_only', legacy_issuer: 'builtin:directory', dual_until: null, window_started_at: null }
  let suite = { suite_id: 'acme', hub_issuer: null as string | null, join_state: 'planned', migration }
  let keycloakResponse = { ...keycloak, active: true }
  const patch = vi.fn()
  const put = vi.fn()
  open('suite', (path, method, body) => {
    if (path === project + '/auth') {
      if (method === 'PATCH') { patch(body); suite = (body as { suite: typeof suite }).suite }
      return Response.json({ ...auth, provider: 'keycloak', suite })
    }
    if (path === project + '/keycloak') {
      if (method === 'PUT') {
        put(body)
        if (put.mock.calls.length === 1) return Response.json({ code: 'unavailable', details: [] }, { status: 503 })
        keycloakResponse = { ...keycloakResponse, mode: 'shared', realm: 'suite-acme' }
      }
      return Response.json(keycloakResponse)
    }
  })
  const issuer = await screen.findByRole('textbox', { name: 'Hub issuer (optional)' })
  await waitFor(() => expect((issuer as HTMLInputElement).disabled).toBe(false))
  expect((screen.getByRole('textbox', { name: 'Suite id' }) as HTMLInputElement).disabled).toBe(true)
  expect((screen.getByRole('button', { name: 'Remove from suite' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.change(issuer, { target: { value: 'https://login.example.test/realms/suite-acme' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByText('The suite was saved, but Keycloak was not updated.')).toBeTruthy()
  fireEvent.click(await screen.findByRole('button', { name: 'Retry Keycloak update' }))
  expect(await screen.findByText('Saved.')).toBeTruthy()
  expect(patch.mock.calls).toEqual([[{ suite: { ...suite, migration } }]])
  expect(put).toHaveBeenCalledTimes(2)
})
