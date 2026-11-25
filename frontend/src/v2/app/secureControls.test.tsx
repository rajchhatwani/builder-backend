// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { entryKeys } from '../features/entry/api/entry'
import { App } from './App'
import { createAppRouter } from './router'

const project = '/projects/secure-unit'
const user = { id: 'owner', name: 'Owner', email: 'owner@example.test', platform_role: 'customer', email_verified_at: '2026-01-01' }
const spec = { auth: { enabled: true, roles: [] }, entities: [] }
const fields = [{ entity: 'Employee', field: 'email', read_roles: [], write_roles: null }]
type Handler = (path: string, method: string, body: unknown) => Response | undefined

function open(section: string, handle: Handler, role = 'owner') {
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
    const { pathname } = new URL(url)
    const body: unknown = typeof options?.body === 'string' ? JSON.parse(options.body) : undefined
    const override = handle(pathname, options?.method ?? 'GET', body)
    if (override) return override
    if (pathname === project) return Response.json({ id: 'secure-unit', name: 'Directory', slug: 'directory' })
    if (pathname === project + '/members') return Response.json([{ user_id: user.id, role }])
    if (pathname === project + '/status') return Response.json({ ready: true, sections: [], issues: [], counts: {} })
    if (pathname === project + '/spec') return Response.json(spec)
    if (pathname === project + '/roles') return Response.json({ items: [], total: 0 })
    if (pathname === project + '/authorization/issues' || pathname === project + '/behavior/issues') return Response.json({ issues: [] })
    if (pathname === project + '/behavior/roles') return Response.json({ roles: [{ name: 'admin', label: 'Admin' }] })
    return Response.json({ code: 'not_found', details: [] }, { status: 404 })
  }))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(entryKeys.session(), user)
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [project + '/' + section] }))
  render(<App queryClient={queryClient} router={router} />)
  return router
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

it('Authorization requires a second confirmation for a widened versioned write', async () => {
  const writes: unknown[] = []
  let config = { project_id: 'secure-unit', model: 'rbac', policies: [], attachments: {}, field_access: fields, version: 4, updated_at: null }
  open('access', (path, method, body) => {
    if (path !== project + '/authorization') return
    if (method === 'PUT') {
      writes.push(body)
      if (writes.length === 1) return Response.json({ code: 'access_weakened', details: [
        { role: 'member', entity: 'Employee', target: 'get', before: 'no', after: 'yes' },
      ] }, { status: 409 })
      config = { ...config, model: 'abac', version: 5 }
    }
    return Response.json(config)
  })
  const model = await screen.findByRole('button', { name: 'Attribute rules (ABAC)' })
  await waitFor(() => expect(model).not.toHaveProperty('disabled', true))
  fireEvent.click(model)
  fireEvent.click(screen.getByRole('button', { name: /^Save$/ }))
  const review = await screen.findByRole('dialog', { name: 'This gives some roles more access' })
  expect(within(review).getByText(/member · Employee · get/)).toBeTruthy()
  const body = { expected_version: 4, model: 'abac', policies: [], attachments: {}, field_access: fields }
  expect(writes).toEqual([{ ...body, confirm_weakening: false }])
  fireEvent.click(within(review).getByRole('button', { name: 'Save anyway' }))
  await waitFor(() => expect(writes.at(1)).toEqual({ ...body, confirm_weakening: true }))
  expect(await screen.findByRole('tab', { name: 'Policies' })).toBeTruthy()
})

it('Dependencies validates exact versions and sends recorded hashes for review', async () => {
  const hash = 'sha256:' + 'f'.repeat(64)
  const writes: unknown[] = []
  open('dependencies', (path, method, body) => {
    if (path === project + '/dependencies') return Response.json({ curated_sets: {}, approved: [], allow_list: [], pending_requests: 0 })
    if (path === project + '/dependencies/requests') {
      if (method === 'POST') writes.push(body)
      return Response.json(method === 'POST' ? body : [])
    }
    if (path.startsWith(project + '/registry/')) return Response.json([])
  })
  const submit = await screen.findByRole('button', { name: 'Send request' })
  fireEvent.change(screen.getByRole('textbox', { name: 'Package' }), { target: { value: 'httpx' } })
  const version = screen.getByRole('textbox', { name: 'Version' })
  fireEvent.change(version, { target: { value: '>=1' } })
  fireEvent.change(screen.getByRole('textbox', { name: 'Why do you need it?' }), { target: { value: 'Example integration' } })
  fireEvent.change(screen.getByRole('textbox', { name: 'SHA-256 hashes (optional)' }), { target: { value: hash } })
  fireEvent.click(submit)
  expect(await screen.findByText('Enter one exact version like 1.2.3.')).toBeTruthy()
  expect(writes).toEqual([])
  fireEvent.change(version, { target: { value: '0.28.1' } })
  fireEvent.click(submit)
  expect(await screen.findByText('Request list updated.')).toBeTruthy()
  expect(writes).toEqual([{ package: 'httpx', version: '0.28.1', reason: 'Example integration', hashes: [hash] }])
})

it('Compliance reloads a conflicting version before accepting a new save', async () => {
  const writes: unknown[] = []
  let version = 1
  let compliance = {
    enabled: false, roles: [], retention: [], consent_purposes: [],
    break_glass: { enabled: false, roles: [], max_minutes: 60 },
    export_entities: [], export_fields: [], export_consent_purpose: null,
  }
  open('compliance?tab=settings', (path, method, body) => {
    if (path !== project + '/behavior/compliance') return
    if (method === 'PUT') {
      writes.push(body)
      version++
      if (writes.length === 1) return Response.json({ code: 'conflict', details: [] }, { status: 409 })
      compliance = (body as { compliance: typeof compliance }).compliance
    }
    return Response.json({ compliance, version, row_version: version, updated_at: null })
  })
  const purposes = await screen.findByRole('textbox', { name: 'Purposes (comma separated)' })
  await waitFor(() => expect(purposes).not.toHaveProperty('disabled', true))
  fireEvent.change(purposes, { target: { value: 'analytics' } })
  fireEvent.click(screen.getByRole('button', { name: /^Save$/ }))
  fireEvent.click(await screen.findByRole('button', { name: 'Reload' }))
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Reload' })).toBeNull())
  const reloaded = screen.getByRole('textbox', { name: 'Purposes (comma separated)' })
  expect(reloaded).toHaveProperty('value', '')
  fireEvent.change(reloaded, { target: { value: 'analytics, research' } })
  fireEvent.click(screen.getByRole('button', { name: /^Save$/ }))
  expect(await screen.findByText('Saved (version 3).')).toBeTruthy()
  expect(writes).toEqual([
    { expected_version: 1, compliance: expect.objectContaining({ consent_purposes: ['analytics'] }) },
    { expected_version: 2, compliance: expect.objectContaining({ consent_purposes: ['analytics', 'research'] }) },
  ])
})
