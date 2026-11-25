// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { entryKeys } from '../features/entry/api/entry'
import { App } from './App'
import { normalizeEntryAddress } from './entryCompatibility'
import { createAppRouter } from './router'

const email = 'reader@example.test'
const user = { id: 'user', email, email_verified_at: '2026-11-21T12:00:00Z' }
const org = { id: 'org', name: 'City Library', slug: 'city-library' }
const emptyPage = { items: [], total: 0, limit: 0, offset: 0 }
const success = (data: unknown, status = 200) => Response.json(data, { status })
const refusal = (code: string, status: number, message = '') => success({ code, message, details: [] }, status)

function open(path: string, handle?: (path: string, request?: RequestInit) => Response | undefined, signedIn = false) {
  const fetch = vi.fn(async (url: string, request?: RequestInit) => {
    const { pathname } = new URL(url)
    return handle?.(pathname, request) ?? (pathname === '/account/refresh' || pathname === '/account/me'
      ? refusal('unauthorized', 401) : success(emptyPage))
  })
  vi.stubGlobal('fetch', fetch)
  const client = new QueryClient()
  if (signedIn) client.setQueryData(entryKeys.session(), user)
  const router = createAppRouter(client, createMemoryHistory({ initialEntries: [path] }))
  render(<StrictMode><App queryClient={client} router={router} /></StrictMode>)
  return { router, fetch }
}

function fill(name: string, value: string) {
  fireEvent.change(screen.getByLabelText(name, { exact: true }), { target: { value } })
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('v2-language', 'en')
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})
afterEach(() => {
  cleanup()
  history.replaceState(null, '', '/')
  vi.unstubAllGlobals()
})

it('opens Login after an anonymous Projects visit and routes the discovered account to SSO with a password fallback', async () => {
  const { router } = open('/projects', path => path === '/account/login/discover'
    ? success({ method: 'sso', organization_name: 'City Library', login_url: 'https://api.example.test/sso/library/login' }) : undefined)
  await screen.findByLabelText('Email')
  expect(router.state.location.pathname).toBe('/login')
  fill('Email', email)
  fireEvent.click(screen.getByRole('button', { name: /^Continue$/ }))
  expect(await screen.findByRole('button', { name: 'Continue with City Library SSO' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Sign in with a password instead' }))
  expect(screen.getByLabelText('Password')).toBeTruthy()
})

it('completes password and recovery-code MFA from Sign in', async () => {
  const { router, fetch } = open('/signin', path => {
    if (path.endsWith('/discover')) return success({ method: 'password' })
    if (path.endsWith('/login')) return success({
      mfa_required: true, enrollment_required: false, mfa_token: 'challenge', expires_in: 300, methods: ['totp', 'recovery_code'],
    })
    if (path.endsWith('/mfa')) return success({ user, access_token: 'fixture' })
  })
  await screen.findByLabelText('Email')
  fill('Email', email)
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
  await screen.findByLabelText('Password')
  fill('Password', 'correct password')
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  await screen.findByLabelText('6-digit code (or a recovery code)')
  fill('6-digit code (or a recovery code)', 'ABCD-EFGH')
  fireEvent.click(screen.getByRole('button', { name: 'Verify' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/projects'))
  expect(fetch.mock.calls.find(([url]) => url.endsWith('/mfa'))?.[1]?.body).toBe(JSON.stringify({
    mfa_token: 'challenge', code: 'ABCD-EFGH',
  }))
})

it('validates sign-up fields and starts the resend cooldown after registration', async () => {
  const { fetch } = open('/signup', path => path === '/account/register' ? success({ status: 'verification_sent' }, 202) : undefined)
  await screen.findByLabelText('Email')
  fireEvent.click(screen.getByRole('button', { name: 'Create account' }))
  expect(document.activeElement).toBe(screen.getByLabelText('Email'))
  fill('Email', 'enrollment@example.test')
  fill('Password', 'Dancing-tables-256')
  fireEvent.click(screen.getByRole('button', { name: 'Create account' }))
  expect(await screen.findByTestId('check-inbox')).toBeTruthy()
  expect((screen.getByTestId('resend') as HTMLButtonElement).disabled).toBe(true)
  expect(fetch.mock.calls.filter(([url]) => url.endsWith('/register'))).toHaveLength(1)
})

it('verifies an email token once under StrictMode and removes it from the URL', async () => {
  const token = 'verify-library-12345'
  const { router, fetch } = open('/verify-email?token=' + token)
  expect(await screen.findByTestId('verify-ok')).toBeTruthy()
  expect(router.state.location.href).toBe('/verify-email')
  expect(fetch.mock.calls.filter(([url]) => url.endsWith('/verify-email')).map(([, request]) => request?.body))
    .toEqual([JSON.stringify({ token })])
})

it('adopts the SSO cookie session and returns to the invitations list', async () => {
  const { router } = open('/sso/complete?next=invitations', path => {
    if (path === '/account/refresh') return success({ access_token: 'fixture' })
    if (path === '/account/me') return success(user)
  })
  await screen.findByRole('heading', { name: 'Invitations' })
  expect(router.state.location.pathname).toBe('/invitations')
})

it('shows an invitation conflict, refreshes the list and permits a valid pasted link', async () => {
  let initial = true
  const { router, fetch } = open('/invitations', path => {
    if (path.endsWith('/pending')) return success({ ...emptyPage, total: 1, items: [{
      id: 'first', organization_name: org.name, role: 'member', expires_at: '2099-01-01', created_at: '2026-11-21',
    }] })
    if (path.endsWith('/first/accept')) return refusal('invalid_token', 409, 'invitation already accepted')
    if (path.endsWith('/invitations/accept')) return success(org)
    if (path === '/account/me') return success(user)
    if (path === '/orgs/city-library') return success(org)
    if (path === '/orgs' && initial) { initial = false; return success(emptyPage) }
  }, true)
  fireEvent.click(await screen.findByRole('button', { name: 'Accept invitation from City Library' }))
  expect(await screen.findByText('Invitation already accepted.')).toBeTruthy()
  fill('Invite link', 'https://app.example.test/#/invite/%E0%A4%A')
  fireEvent.click(screen.getByRole('button', { name: 'Join' }))
  expect(await screen.findByText('Enter the invite link or token you were sent.')).toBeTruthy()
  fill('Invite link', 'https://app.example.test/#/invite/city-library-invite-token')
  fireEvent.click(screen.getByRole('button', { name: 'Join' }))
  await screen.findByRole('heading', { name: 'City Library' })
  expect(router.state.location.pathname).toBe('/org/city-library')
  expect(fetch.mock.calls.find(([url]) => url.endsWith('/invitations/accept'))?.[1]?.body)
    .toBe(JSON.stringify({ token: 'city-library-invite-token' }))
})

it('exchanges an issued verification fragment for a path without exposing the token to the router', async () => {
  history.replaceState(null, '', '/#/verify-email?token=legacy-confirmation-token')
  normalizeEntryAddress()
  expect(location.pathname + location.search + location.hash).toBe('/verify-email')
  const { fetch } = open('/verify-email')
  await screen.findByTestId('verify-ok')
  expect(fetch.mock.calls[0]?.[1]?.body).toBe(JSON.stringify({ token: 'legacy-confirmation-token' }))
})

it('returns to an issued invitation after password sign-in and removes the link on accept', async () => {
  const token = 'city-library-email-link'
  history.replaceState(null, '', '/#/invite/' + token)
  normalizeEntryAddress()
  expect(location.pathname + location.hash).toBe('/invitations')
  let signedIn = false
  const { router, fetch } = open('/invitations', path => {
    if (path.endsWith('/discover')) return success({ method: 'password' })
    if (path === '/account/login') {
      signedIn = true
      return success({ user, access_token: 'fixture' })
    }
    if (path === '/account/me' && signedIn) return success(user)
    if (path === '/orgs/invitations/accept' || path === '/orgs/city-library') return success(org)
  })
  await screen.findByLabelText('Email')
  expect(router.state.location.search).toMatchObject({ next: 'invitations' })
  fill('Email', email)
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
  await screen.findByLabelText('Password')
  fill('Password', 'correct password')
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  fireEvent.click(await screen.findByRole('button', { name: /^Accept invitation$/ }))
  await screen.findByRole('heading', { name: 'City Library' })
  expect(router.state.location.href).toBe('/org/city-library')
  expect(fetch.mock.calls.find(([url]) => url.endsWith('/invitations/accept'))?.[1]?.body).toBe(JSON.stringify({ token }))
})

it('keeps a temporary password account out of a direct project link', async () => {
  const { fetch } = open('/projects/project-one/code', path => {
    if (path === '/account/me') return success({ ...user, must_change_password: true })
    if (path === '/account/refresh') return success({ access_token: 'fixture' })
  })
  expect(await screen.findByRole('heading', { name: 'Choose a new password' })).toBeTruthy()
  expect(fetch.mock.calls.some(([url]) => new URL(url).pathname.startsWith('/projects/'))).toBe(false)
})
