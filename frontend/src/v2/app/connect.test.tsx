// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { members, model, payments, root, sizing, storage, token, user } from '../../../e2e/v2/fixtures/connect-a'
import { entryKeys } from '../features/entry/api/entry'
import { App } from './App'
import { createAppRouter } from './router'

type Handler = (path: string, method: string, body: unknown) => Response | undefined

function open(section: string, handler: Handler, role = 'owner') {
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
    const { pathname } = new URL(url)
    const body: unknown = typeof options?.body === 'string' ? JSON.parse(options.body) : undefined
    const result = handler(pathname, options?.method ?? 'GET', body)
    if (result) return result
    if (pathname === root) return Response.json({ name: 'Invoices', slug: 'invoices' })
    if (pathname === root + '/members') return Response.json(members.map(member => member.user_id === user.id ? { ...member, role } : member))
    if (pathname === root + '/status') return Response.json({ ready: true, sections: [], issues: [], counts: {} })
    if (pathname === root + '/spec') return Response.json(model)
    if (pathname === root + '/payments') return Response.json(payments)
    if (pathname === root + '/payments/sizing') return Response.json({ sizing, issues: [] })
    if (pathname === root + '/storage') return Response.json(storage)
    if (pathname === root + '/tokens') return Response.json([token])
    return Response.json({ code: 'not_found', details: [] }, { status: 404 })
  }))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(entryKeys.session(), user)
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [root + '/' + section] }))
  render(<App router={router} queryClient={queryClient} />)
  return { queryClient, router }
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

it('Payments retains a draft after a rejected whole-document write and maps the server field error', async () => {
  const sent: unknown[] = []
  open('payments?tab=form', (path, method, body) => {
    if (path === root + '/payments' && method === 'PUT') {
      sent.push(body)
      return Response.json({ code: 'validation_error', details: [{ loc: ['body', 'max_amount_minor'], msg: 'Amount is out of range.' }] }, { status: 422 })
    }
  })
  const amount = await screen.findByRole('textbox', { name: 'Largest single payment in the smallest unit' })
  const save = screen.getByRole('button', { name: /^Save$/ })
  await waitFor(() => expect(amount).toHaveProperty('disabled', false))
  fireEvent.change(amount, { target: { value: '2200' } })
  fireEvent.click(save)
  expect(await screen.findByText(/Amount is out of range/)).toBeTruthy()
  expect(amount).toHaveProperty('value', '2200')
  expect(sent).toHaveLength(1)
  expect(sent[0]).toMatchObject({ max_amount_minor: 2200 })
  expect(sent[0]).not.toHaveProperty('enabled')
})

it('File uploads validates MIME entries before writing and shows the file-field dependency', async () => {
  const sent: unknown[] = []
  open('storage?tab=guided', (path, method, body) => {
    if (path === root + '/storage' && method === 'PUT') {
      sent.push(body)
      return Response.json(storage)
    }
  })
  expect(await screen.findByText('Invoice.attachment')).toBeTruthy()
  const mime = screen.getByRole('textbox', { name: /Allowed types/ })
  const save = screen.getByRole('button', { name: 'Save file upload settings' })
  await waitFor(() => expect(mime).toHaveProperty('disabled', false))
  fireEvent.change(mime, { target: { value: '*/*' } })
  fireEvent.click(save)
  expect(await screen.findByText(/is not accepted in Allowed types/)).toBeTruthy()
  expect(sent).toEqual([])
  fireEvent.change(mime, { target: { value: 'text/plain' } })
  fireEvent.click(screen.getByRole('button', { name: '+ PDF' }))
  fireEvent.click(save)
  await waitFor(() => expect(sent[0]).toMatchObject({ bucket: 'invoice-files', allowed_types: ['text/plain', 'application/pdf'] }))
})

it('Integrations pins a personal token and reveals the value without putting it in the query or mutation cache', async () => {
  const secret = 'issued-once-for-test'
  const sent: unknown[] = []
  const { queryClient } = open('integrations', (path, method, body) => {
    if (path === '/account/tokens' && method === 'POST') {
      sent.push(body)
      return Response.json({ ...token, token: secret })
    }
  })
  fireEvent.click(await screen.findByRole('button', { name: 'Create pinned token' }))
  const create = await screen.findByRole('dialog', { name: 'Create pinned token' })
  fireEvent.change(within(create).getByRole('textbox', { name: 'Token name' }), { target: { value: 'My assistant' } })
  fireEvent.click(within(create).getByRole('button', { name: 'Create pinned token' }))
  const revealed = await screen.findByRole('dialog', { name: 'Copy your token' })
  expect(within(revealed).getByText(secret)).toBeTruthy()
  expect(sent).toEqual([{ name: 'My assistant', description: null, project_id: token.project_id, expires_in_days: 90, scopes: ['mcp:read'] }])
  expect(JSON.stringify(queryClient.getQueryCache().getAll().map(item => item.state.data))).not.toContain(secret)
  expect(JSON.stringify(queryClient.getMutationCache().getAll().map(item => item.state.data))).not.toContain(secret)
  const close = within(revealed).getByRole('button', { name: 'I have stored it' })
  await waitFor(() => {
    fireEvent.click(close)
    expect(screen.queryByText(secret)).toBeNull()
  })
})
