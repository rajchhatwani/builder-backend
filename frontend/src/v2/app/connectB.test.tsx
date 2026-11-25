// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { members, projectId, root, user } from '../../../e2e/v2/fixtures/connect-a'
import { app, batch, batchId, blockReply, catalogue, connectSpec, platformPath, preview, previewId, previewPath, settings } from '../../../e2e/v2/fixtures/connect-b'
import type { Setting } from '../../../e2e/v2/fixtures/connect-b'
import { entryKeys } from '../features/entry/api/entry'
import { App } from './App'
import { createAppRouter } from './router'

type Handler = (path: string, method: string, body: unknown) => Response | undefined
function open(section: string, handler: Handler = () => undefined, role = 'owner') {
  const sender = vi.fn(async (url: string, options?: RequestInit) => {
    const { pathname } = new URL(url, window.location.origin)
    const body = typeof options?.body === 'string' ? JSON.parse(options.body) : options?.body
    const response = handler(pathname, options?.method ?? 'GET', body)
    if (response) return response
    if (pathname === '/account/me') return Response.json(user)
    if (pathname === '/orgs') return Response.json({ items: [], total: 0 })
    if (pathname === root) return Response.json({ id: projectId, name: 'Invoices', slug: 'invoices', version: 1 })
    if (pathname === root + '/status') return Response.json({ ready: true, sections: [], issues: [], counts: {} })
    if (pathname === root + '/members') return Response.json(members.map(member => member.user_id === user.id ? { ...member, role } : member))
    if (pathname === root + '/workspaces') return Response.json([])
    if (pathname === root + '/spec') return Response.json(connectSpec)
    if (pathname === root + '/behavior/roles') return Response.json({ roles: connectSpec.auth.roles })
    if (pathname === root + '/behavior/issues') return Response.json({ issues: [] })
    const block = pathname.split('/').at(-1) as Setting
    if (pathname === root + '/behavior/' + block && Object.hasOwn(settings, block)) return Response.json(blockReply(block, settings[block]))
    return Response.json({ code: 'not_found', details: [] }, { status: 404 })
  })
  vi.stubGlobal('fetch', sender)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(entryKeys.session(), user)
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [root + '/' + section] }))
  render(<App router={router} queryClient={queryClient} />)
  return { queryClient, router, sender }
}
beforeEach(() => {
  localStorage.setItem('v2-language', 'en')
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})
afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals() })

it('Providers masks legacy credentials, validates JSON, and saves with the loaded version', async () => {
  const writes: unknown[] = []
  open('providers', (path, method, body) => {
    if (path !== root + '/behavior/providers') return
    if (method === 'GET') return Response.json(blockReply('providers', { ...settings.providers,
      adapters: [{ kind: 'email', name: 'mail', settings: { region: 'eu', api_key: 'fixture-value' } }],
    }))
    writes.push(body)
    return Response.json(blockReply('providers', (body as { providers: unknown }).providers, 4))
  })
  const editor = await screen.findByRole('textbox', { name: 'Settings' }, { timeout: 4000 })
  await waitFor(() => expect(editor).toHaveProperty('readOnly', false))
  expect(editor).toHaveProperty('value', '{\n  "region": "eu"\n}')
  const save = screen.getByRole('button', { name: /^Save$/ })
  fireEvent.change(editor, { target: { value: '{' } })
  expect(await screen.findByText('Not valid JSON. Fix it before saving.')).toBeTruthy()
  expect(writes).toHaveLength(0)
  fireEvent.change(editor, { target: { value: '{"region":"us"}' } })
  fireEvent.click(save)
  expect(await screen.findByText('Saved (version 4).')).toBeTruthy()
  expect(writes).toMatchObject([{ expected_version: 3, providers: { adapters: [{ settings: { region: 'us' } }] } }])
})

it('API edge turns a nullable part off and reloads after a conflict', async () => {
  const writes: unknown[] = []
  let version = 3
  open('apiedge', (path, method, body) => {
    if (path !== root + '/behavior/api-edge') return
    const edge = { ...settings['api-edge'], quotas: [{ meter: 'reads', period: 'day', limit: 10, path_prefix: '/', methods: [], cost: 1 }] }
    if (method === 'GET') return Response.json(blockReply('api-edge', edge, version))
    writes.push(body)
    version = 4
    return Response.json({ code: 'conflict', message: 'Version changed.', details: [] }, { status: 409 })
  })
  const toggle = await screen.findByRole('checkbox', { name: 'Include Idempotency' }, { timeout: 4000 })
  await waitFor(() => expect(toggle).toHaveProperty('disabled', false))
  fireEvent.click(toggle)
  fireEvent.click(screen.getByRole('button', { name: /^Save$/ }))
  const reload = await screen.findByRole('button', { name: /^Reload$/ })
  expect(toggle).toHaveProperty('checked', false)
  expect(writes).toMatchObject([{ expected_version: 3, api_edge: { idempotency: null } }])
  fireEvent.click(reload)
  await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Include Idempotency' })).toHaveProperty('checked', true))
})

it('Import loads a bookmarked batch and gives viewers a read-only review', async () => {
  open('import?batch=' + batchId + '&view=review', path => {
    if (path === root + '/imports/' + batchId) return Response.json(batch)
    if (path === root + '/imports/' + batchId + '/rows') return Response.json({ items: batch.rejected, total: 1 })
  }, 'viewer')
  expect(await screen.findByText('reference: at most 2 characters', {}, { timeout: 4000 })).toBeTruthy()
  expect(screen.getByRole('textbox', { name: 'Fix reference (row 1)' })).toHaveProperty('disabled', true)
  expect(screen.queryByRole('button', { name: 'Cancel import' })).toBeNull()
})

it('API keys persists public settings at the hyphenated endpoint', async () => {
  const writes: unknown[] = []
  open('apikeys', (path, method, body) => {
    if (path === root + '/behavior/api-platform' && method === 'PUT') {
      writes.push(body)
      return Response.json(blockReply('api-platform', (body as { api_platform: unknown }).api_platform, 4))
    }
  })
  const ttl = await screen.findByRole('spinbutton', { name: 'Key lifetime (days)' }, { timeout: 4000 })
  await waitFor(() => expect(ttl).toHaveProperty('readOnly', false))
  fireEvent.change(ttl, { target: { value: '30' } })
  fireEvent.click(screen.getByRole('button', { name: /^Save$/ }))
  expect(await screen.findByText('Saved (version 4).')).toBeTruthy()
  expect(writes).toMatchObject([{ expected_version: 3, api_platform: { key_ttl_days: 30 } }])
})

it('Apps installs only selected scopes and keeps the one-time credentials out of query data', async () => {
  const writes: unknown[] = []
  const { sender, router, queryClient } = open('see?preview=' + previewId, (path, method, body) => {
    if (path === root + '/previews') return Response.json([preview])
    if (path === root + previewPath) return Response.json(preview)
    if (path === root + previewPath + '/rotate-token' && method === 'POST') return Response.json({ ...preview, token: 'preview-token' })
    if (path === previewPath + '/auth/login') return Response.json({ access_token: 'generated-admin' })
    if (path === previewPath + '/openapi.json') return Response.json({ paths: {} })
    if (path === platformPath + '/catalogue') return Response.json(catalogue)
    if (path === platformPath + '/keys') return Response.json([])
    if (path === platformPath + '/apps') return Response.json([app])
    if (path === platformPath + '/apps/reporter/install') {
      writes.push(body)
      return Response.json({ installation_id: 'install-1', app: 'reporter', granted_scopes: ['Invoice'],
        token: 'visible-app-token', signing_secret: 'visible-signing-secret' })
    }
  })
  fireEvent.click(await screen.findByRole('button', { name: 'Reconnect' }, { timeout: 5000 }))
  fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Confirm' }))
  expect(await screen.findByRole('button', { name: 'Sign in to preview' })).toBeTruthy()
  await act(async () => { await router.navigate({ to: '/projects/$projectId/$section', params: { projectId, section: 'apps' }, search: { preview: previewId } }) })
  fireEvent.click(await screen.findByRole('button', { name: 'Sign in to preview' }))
  const login = await screen.findByRole('dialog')
  fireEvent.change(within(login).getByLabelText('Preview account email'), { target: { value: 'admin@example.test' } })
  fireEvent.change(within(login).getByLabelText('Preview password'), { target: { value: 'Password123' } })
  fireEvent.click(within(login).getByRole('button', { name: 'Sign in to preview' }))
  const scopes = await screen.findAllByTestId('app-scope')
  fireEvent.click(scopes[1])
  fireEvent.click(screen.getByRole('button', { name: 'Install Reporter' }))
  expect(await screen.findByText('visible-app-token')).toBeTruthy()
  expect(writes).toEqual([{ scopes: ['Invoice'] }])
  expect(sender.mock.calls.find(([url]) => url.endsWith('/install'))?.[1]).toMatchObject({
    redirect: 'error', credentials: 'omit', headers: { Authorization: 'Bearer generated-admin', 'X-Preview-Token': 'preview-token' },
  })
  expect(JSON.stringify(queryClient.getQueryCache().getAll().map(query => query.state.data))).not.toContain('visible-app-token')
  expect(JSON.stringify(queryClient.getMutationCache().getAll().map(mutation => mutation.state.data))).not.toContain('visible-signing-secret')
  fireEvent.click(screen.getByTestId('secret-dismiss'))
  await waitFor(() => expect(screen.queryByTestId('secret-panel')).toBeNull())
}, 10_000)
