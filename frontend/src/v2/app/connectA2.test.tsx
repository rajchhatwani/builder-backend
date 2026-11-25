// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { members, projectId, root, user } from '../../../e2e/v2/fixtures/connect-a'
import { blockReply, blocks, notifications, spec, webhooks } from '../../../e2e/v2/fixtures/connect-a2'
import type { Block } from '../../../e2e/v2/fixtures/connect-a2'
import { entryKeys } from '../features/entry/api/entry'
import { App } from './App'
import { createAppRouter } from './router'

type Handler = (path: string, method: string, body: unknown) => Response | undefined
function open(section: string, handler: Handler = () => undefined, projectRole = 'owner') {
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    const { pathname } = new URL(url)
    const body: unknown = typeof options?.body === 'string' ? JSON.parse(options.body) : undefined
    const response = handler(pathname, options?.method ?? 'GET', body)
    if (response) return response
    if (pathname === '/account/me') return Response.json(user)
    if (pathname === root + '/workspaces') return Response.json([])
    if (pathname === root) return Response.json({ name: 'Invoices', slug: 'invoices' })
    if (pathname === root + '/members') return Response.json(members.map(member => member.user_id === user.id ? { ...member, role: projectRole } : member))
    if (pathname === root + '/status') return Response.json({ ready: true, sections: [], issues: [], counts: {} })
    if (pathname === root + '/spec') return Response.json(spec)
    if (pathname === root + '/behavior/roles') return Response.json({ roles: spec.auth.roles })
    if (pathname === root + '/behavior/issues') return Response.json({ issues: [] })
    const name = pathname.split('/').at(-1) as Block
    if (pathname === root + '/behavior/' + name && Object.hasOwn(blocks, name)) return Response.json(blockReply(name, blocks[name]))
    return Response.json({ code: 'not_found', details: [] }, { status: 404 })
  })
  vi.stubGlobal('fetch', fetch)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(entryKeys.session(), user)
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [root + '/' + section] }))
  render(<App router={router} queryClient={queryClient} />)
  return { fetch, router, queryClient }
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

it('Forms preview shows local backend messages verbatim and keeps hidden fields in its value', async () => {
  const { fetch } = open('forms')
  const service = await screen.findByRole('textbox', { name: 'Service name' }, { timeout: 4000 })
  fireEvent.change(service, { target: { value: 'invoice-service' } })
  fireEvent.click(screen.getByRole('button', { name: 'Show sample backend errors' }))
  expect(await screen.findByText('String should have at most 80 characters')).toBeTruthy()
  expect(service.getAttribute('aria-invalid')).toBe('true')
  fireEvent.click(screen.getByRole('checkbox', { name: 'Enabled' }))
  expect(screen.queryByRole('textbox', { name: 'Service name' })).toBeNull()
  expect(screen.getByTestId('form-value').textContent).toContain('invoice-service')
  expect(fetch.mock.calls.map(([url]) => url).some(url => url.includes('/behavior/'))).toBe(false)
})

it('Notifications validates placeholders then preserves the template draft through a version conflict', async () => {
  const writes: unknown[] = []
  let version = 3
  open('notifications', (path, method, body) => {
    if (path !== root + '/behavior/notifications') return
    if (method === 'GET') return Response.json(blockReply('notifications', notifications, version))
    writes.push(body)
    version = 4
    return Response.json({ code: 'version_conflict', message: 'version changed', details: [] }, { status: 409 })
  })
  const body = await screen.findByRole('textbox', { name: 'Message body' })
  await waitFor(() => expect(body).toHaveProperty('disabled', false))
  const save = screen.getByRole('button', { name: 'Save template' })
  fireEvent.change(body, { target: { value: 'Invoice for {{ unknown }}' } })
  fireEvent.click(save)
  expect(await screen.findByText('Unknown variables: unknown.')).toBeTruthy()
  expect(writes).toEqual([])
  fireEvent.change(body, { target: { value: 'Invoice for {{ customer }}' } })
  fireEvent.click(save)
  const reload = await screen.findByRole('button', { name: /^Reload$/ })
  expect(body).toHaveProperty('value', 'Invoice for {{ customer }}')
  expect(writes[0]).toMatchObject({ expected_version: 3, notifications: { types: [{ templates: [
    { body: 'Invoice for {{ customer }}' }, { channel: 'sms' },
  ] }] } })
  fireEvent.click(reload)
  await waitFor(() => expect(body).toHaveProperty('value', 'Your invoice is ready.'))
})

it('Notification types removes the entire block only after confirmation', async () => {
  const writes: unknown[] = []
  open('notiftypes', (path, method, body) => {
    if (path === root + '/behavior/notifications' && method === 'PUT') {
      writes.push(body)
      return Response.json(blockReply('notifications', null, 4))
    }
  })
  const action = await screen.findByRole('button', { name: 'Remove notifications settings' })
  fireEvent.click(action)
  const dialog = await screen.findByRole('dialog', { name: 'Remove notifications settings?' })
  expect(writes).toEqual([])
  fireEvent.click(within(dialog).getByRole('button', { name: 'Remove settings' }))
  expect(await screen.findByText('Saved (version 4).')).toBeTruthy()
  expect(writes).toEqual([{ notifications: null, expected_version: 3 }])
})

it('Webhooks shows the saved receiver and handler link to viewers without write controls', async () => {
  open('webhooks', undefined, 'viewer')
  expect(await screen.findByText('/webhooks/in/invoice_status')).toBeTruthy()
  expect(await screen.findByText('You can look at this but not change it. Your role is viewer.')).toBeTruthy()
  const handler = screen.getByRole('link', { name: 'Open webhook handlers in the editor' })
  expect(handler.getAttribute('href')).toContain('file=app%2Fhooks%2Fwebhooks.py')
  expect(screen.queryByRole('button', { name: /^Save$/ })).toBeNull()
  expect(screen.getByRole('spinbutton', { name: 'Timeout seconds' })).toHaveProperty('value', String(webhooks.timeout_seconds))
})

it('Webhooks connects through the project preview and keeps the revealed secret out of query and mutation data', async () => {
  const previewId = 'c4e1a466-1ed2-4711-b4bf-6a221f2c8a74'
  const previewPath = '/previews/' + previewId
  const preview = {
    id: previewId, state: 'running', is_preview: true, workspace_id: null, url_path: previewPath,
    created_at: '2026-01-10T12:00:00Z', last_request_at: '2026-01-10T12:00:00Z', expires_at: '2026-01-10T12:00:00Z', limits: {},
  }
  const row = {
    id: 'subscription-1', url: 'https://hooks.example.test/invoices', description: '', event_types: ['invoice.created'],
    status: 'active', disabled_reason: null, consecutive_failures: 0, secret_version: 1, rotating: false, created_at: preview.created_at,
  }
  const secret = 'whsec_fixture_revealed_once'
  const sub = previewPath + '/webhooks/subscriptions'
  const writes: unknown[] = []
  const { fetch, router, queryClient } = open('see?preview=' + previewId, (path, method, body) => {
    if (path === root + '/previews') return Response.json([preview])
    if (path === root + previewPath) return Response.json(preview)
    if (path === root + previewPath + '/rotate-token' && method === 'POST') return Response.json({ ...preview, token: 'preview-token' })
    if (path === previewPath + '/openapi.json') return Response.json({ paths: {} })
    if (path === previewPath + '/webhooks/events') return Response.json(['invoice.created'])
    if (path === previewPath + '/webhooks/inbound') return Response.json([])
    if (path === sub) return Response.json([row])
    if (path === sub + '/' + row.id) return Response.json(row)
    if (path === sub + '/' + row.id + '/rotate' && method === 'POST') {
      writes.push(body)
      return Response.json({ ...row, secret })
    }
  })
  fireEvent.click(await screen.findByRole('button', { name: 'Reconnect' }, { timeout: 4000 }))
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'Issue a new token' })).getByRole('button', { name: 'Confirm' }))
  expect(await screen.findByRole('button', { name: 'Sign in to preview' })).toBeTruthy()
  await act(async () => { await router.navigate({
    to: '/projects/$projectId/$section', params: { projectId, section: 'webhooks' }, search: { tab: 'subscriptions', preview: previewId },
  }) })
  const bearer = await screen.findByLabelText('Admin bearer token')
  fireEvent.change(bearer, { target: { value: 'generated-admin' } })
  fireEvent.click(screen.getByRole('button', { name: 'Load subscriptions' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Details' }))
  const details = await screen.findByRole('dialog', { name: 'Subscription details' })
  fireEvent.click(await within(details).findByRole('button', { name: 'Rotate secret' }))
  const rotation = await screen.findByRole('dialog', { name: 'Rotate signing secret?' })
  fireEvent.change(within(rotation).getByRole('spinbutton', { name: 'Overlap hours' }), { target: { value: '36' } })
  fireEvent.click(within(rotation).getByRole('button', { name: 'Rotate secret' }))
  const revealed = await screen.findByRole('dialog', { name: 'Signing secret' })
  expect(within(revealed).getByText(secret)).toBeTruthy()
  expect(writes).toEqual([{ overlap_hours: 36 }])
  expect(fetch.mock.calls.find(([url]) => url.endsWith('/rotate'))?.[1]).toMatchObject({
    credentials: 'omit', redirect: 'error', headers: { Authorization: 'Bearer generated-admin', 'X-Preview-Token': 'preview-token' },
  })
  expect(JSON.stringify(queryClient.getQueryCache().getAll().map(query => query.state.data))).not.toContain(secret)
  expect(JSON.stringify(queryClient.getMutationCache().getAll().map(mutation => mutation.state.data))).not.toContain(secret)
  fireEvent.click(within(revealed).getByRole('button', { name: 'I stored it' }))
  await waitFor(() => expect(screen.queryByText(secret)).toBeNull())
})
