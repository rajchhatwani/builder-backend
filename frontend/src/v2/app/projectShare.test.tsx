// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { App } from './App'
import { createAppRouter } from './router'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it('keeps a failed add draft and clears the email when a write commits before a failed refresh', async () => {
  const user = { id: 'owner', name: 'Mina Chen', email: 'mina@example.test', platform_role: 'customer' }
  const created_at = '2026-01-10T12:00:00Z'
  const roster = [{ user_id: user.id, name: user.name, email: user.email, role: 'owner', mcp_enabled: false, created_at }]
  const writes: unknown[] = []
  let failRefresh = false
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const path = new URL(url).pathname
    if (path === '/account/refresh') return Response.json({ access_token: 'fixture' })
    if (path === '/account/me') return Response.json(user)
    if (path === '/projects/project') return Response.json({ name: 'Warehouse' })
    if (path.endsWith('/status')) return Response.json({ ready: true, sections: [], counts: {}, issues: [] })
    if (path.endsWith('/members')) {
      if (init?.method !== 'POST') {
        return failRefresh ? Response.json({ code: 'internal_error' }, { status: 500 }) : Response.json(roster)
      }
      const body = JSON.parse(String(init.body))
      writes.push(body)
      if (body.email === 'missing@example.test') return Response.json({ code: 'user_unavailable' }, { status: 404 })
      const member = { ...body, user_id: 'new', name: 'New Teammate', mcp_enabled: false, created_at }
      roster.push(member)
      failRefresh = true
      return Response.json(member, { status: 201 })
    }
    return Response.json({ code: 'not_found' }, { status: 404 })
  }))
  const client = new QueryClient()
  const router = createAppRouter(client, createMemoryHistory({ initialEntries: ['/projects/project/overview'] }))
  render(<App queryClient={client} router={router} />)
  await screen.findByText('Warehouse', { exact: true })
  fireEvent.click(await screen.findByRole('button', { name: 'Share' }))
  const dialog = within(await screen.findByRole('dialog', { name: 'People with access to Warehouse' }))
  expect(await dialog.findByText('Mina Chen (you)')).toBeTruthy()
  const email = dialog.getByRole<HTMLInputElement>('textbox', { name: 'Email' })
  fireEvent.change(email, { target: { value: 'missing@example.test' } })
  fireEvent.click(dialog.getByRole('button', { name: 'Add' }))
  expect(await dialog.findByText('no active account with that e-mail in this organization')).toBeTruthy()
  expect(email.value).toBe('missing@example.test')

  fireEvent.change(email, { target: { value: 'new@example.test' } })
  fireEvent.click(dialog.getByRole('button', { name: 'Add' }))
  expect(await dialog.findByText("Can't load the members.")).toBeTruthy()
  failRefresh = false
  fireEvent.click(dialog.getByRole('button', { name: 'Retry' }))
  expect(await dialog.findByText('New Teammate')).toBeTruthy()
  expect(dialog.getByRole<HTMLInputElement>('textbox', { name: 'Email' }).value).toBe('')
  expect(writes).toEqual([
    { email: 'missing@example.test', role: 'viewer' },
    { email: 'new@example.test', role: 'viewer' },
  ])
}, 15_000)
