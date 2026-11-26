// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { accessDiff, fixture, history, machines, op, pendingPaths, projectRoot, spec } from '../features/build-spec/__tests__/fixtures'
import type { Screen } from '../features/build-spec/__tests__/fixtures'
import { App } from './App'
import { createAppRouter } from './router'

vi.mock('../features/build-spec/components/DiagramAdapter', () => ({ DiagramAdapter: () => null }))

type Handler = (url: URL, options?: RequestInit) => Response | undefined
const okay = (data: unknown) => Response.json(data)
const conflict = () => Response.json({ code: 'conflict', message: 'The section changed', details: [] }, { status: 409 })

function mock(handler?: Handler, role = 'editor') {
  const fetch = vi.fn(async (address: string, options?: RequestInit) => {
    const url = new URL(address)
    const custom = handler?.(url, options)
    if (custom) return custom
    const data = fixture(url.pathname, role)
    return data === undefined ? Response.json({ code: 'not_found' }, { status: 404 }) : okay(data)
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}
function open(section: Screen, search = '') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createAppRouter(client, createMemoryHistory({ initialEntries: [projectRoot + '/' + section + search] }))
  render(<App queryClient={client} router={router} />)
  return router
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('v2-language', 'en')
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('models generated API routes and selects the entity and tab in the URL', async () => {
  mock()
  const router = open('model')
  const breadcrumb = await screen.findByRole('navigation', { name: 'Breadcrumb' })
  await waitFor(() => {
    const current = breadcrumb.querySelectorAll('[aria-current="page"]')
    expect(current).toHaveLength(1)
    expect(current[0].textContent).toContain('Support desk')
    expect(within(screen.getByRole('banner')).getByText('Ready', { exact: true })).toBeTruthy()
  })
  fireEvent.click(await screen.findByRole('button', { name: 'Ticket' }))
  await screen.findByText('title', { exact: true })
  fireEvent.keyDown(screen.getByRole('tab', { name: 'API' }), { key: 'Enter' })
  expect(await screen.findByText('GET /tickets/{item_id}')).toBeTruthy()
  expect(router.state.location.search).toMatchObject({ entity: 'Ticket', tab: 'api' })
  expect(screen.getByRole('checkbox', { name: 'Soft delete (DELETE sets deleted_at)' })).toBeTruthy()
})

it('selects a state transition and saves a machine draft with the original section version', async () => {
  const address = projectRoot + pendingPaths.machines
  const write = vi.fn()
  let saved = machines
  mock((url, options) => {
    if (url.pathname !== address) return
    if (options?.method === 'PUT') {
      const body = JSON.parse(String(options.body))
      write(body)
      saved = body.state_machines
    }
    return okay({ version: saved === machines ? 3 : 4, state_machines: saved })
  })
  const router = open('machines')
  fireEvent.click(await screen.findByRole('button', { name: 'close_ticket' }))
  expect(await screen.findByText('open → closed')).toBeTruthy()
  expect(router.state.location.search.target).toBe('close_ticket')
  const remove = screen.getByRole('button', { name: 'Remove' })
  await waitFor(() => expect(remove.hasAttribute('disabled')).toBe(false))
  fireEvent.click(remove)
  const confirm = await screen.findByRole('dialog', { name: 'Remove transition' })
  fireEvent.click(within(confirm).getByRole('button', { name: 'Remove' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Save' }))
  await waitFor(() => expect(write).toHaveBeenCalledWith({
    expected_version: 3, state_machines: [{ ...machines[0], transitions: [] }],
  }))
})

it('requires review and explicit confirmation before widening access', async () => {
  const write = vi.fn()
  mock((url, options) => {
    if (url.pathname === projectRoot + '/access/diff') return okay(accessDiff)
    if (url.pathname === projectRoot + '/spec' && options?.method === 'PUT') {
      write(url.searchParams.get('expected_version'), url.searchParams.get('confirm_weakening'), JSON.parse(String(options.body)))
      return okay(spec)
    }
  })
  open('permissions')
  const reader = await screen.findByRole('checkbox', { name: 'reader' })
  await waitFor(() => expect(reader.hasAttribute('disabled')).toBe(false))
  fireEvent.click(reader)
  fireEvent.click(await screen.findByRole('button', { name: 'Review changes' }))
  expect(await screen.findByText('reader gains access to Ticket.list.')).toBeTruthy()
  expect(write).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Apply and confirm more access' }))
  const dialog = await screen.findByRole('dialog', { name: 'Confirm more access' })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Apply and confirm more access' }))
  await waitFor(() => expect(write).toHaveBeenCalledWith('5', 'true', expect.objectContaining({
    auth: expect.objectContaining({ permissions: [expect.objectContaining({ roles: ['staff', 'reader'] })] }),
  })))
})

it('compares a linked historical baseline and allows saving a browser snapshot', async () => {
  mock()
  open('specdiff', '?base=1')
  expect(await screen.findByText('1 difference')).toBeTruthy()
  expect(await screen.findByText('Comment', { exact: true })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Save current spec as baseline' }))
  expect(await screen.findByText('No differences')).toBeTruthy()
})

it('restores the selected timeline version only after confirmation', async () => {
  const restore = vi.fn()
  mock((url, options) => {
    if (url.pathname !== projectRoot + '/spec/restore') return
    restore(JSON.parse(String(options?.body)))
    return okay({ ...op, seq: 3, origin: 'restore', ref_seq: 0 })
  })
  open('timeline')
  fireEvent.click(await screen.findByRole('button', { name: 'Start / before the first change' }))
  expect(await screen.findByText('Restoring takes back 2 changes.')).toBeTruthy()
  expect(screen.getByRole('link', { name: 'Compare with now' }).getAttribute('href')).toContain('base=0')
  const trigger = screen.getByRole('button', { name: 'Restore the draft to this version…' })
  await waitFor(() => expect(trigger.hasAttribute('disabled')).toBe(false))
  fireEvent.click(trigger)
  expect(restore).not.toHaveBeenCalled()
  const confirmation = await screen.findByRole('dialog', { name: 'Restore the draft to this version…' })
  fireEvent.click(within(confirmation).getByRole('button', { name: 'Restore the draft to this version…' }))
  await waitFor(() => expect(restore).toHaveBeenCalledWith({ to_seq: 0 }))
})

it('keeps the history draft on 409 until the user reloads and blocks protected fields', async () => {
  const write = vi.fn()
  mock((url, options) => {
    if (url.pathname === projectRoot + pendingPaths.history && options?.method === 'PUT') {
      write(JSON.parse(String(options.body)))
      return conflict()
    }
  })
  open('history')
  const retention = await screen.findByRole('spinbutton', { name: 'Keep changes for (days)' })
  await waitFor(() => expect(retention.hasAttribute('disabled')).toBe(false))
  expect(screen.getByRole('checkbox', { name: /^api_secret/ }).hasAttribute('disabled')).toBe(true)
  expect(screen.getByRole('checkbox', { name: /^status ·/ }).hasAttribute('disabled')).toBe(true)
  fireEvent.change(retention, { target: { value: '30' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(write).toHaveBeenCalledWith({ history: [{ ...history[0], retention_days: 30 }], expected_version: 4 }))
  const reload = await screen.findByRole('button', { name: 'Reload' })
  expect((retention as HTMLInputElement).value).toBe('30')
  fireEvent.click(reload)
  await waitFor(() => expect((retention as HTMLInputElement).value).toBe('90'))
})
