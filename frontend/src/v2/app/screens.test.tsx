// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { App } from './App'
import { createAppRouter } from './router'

function renderPath(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
  return router
}

function projectResponse(url: string) {
  const path = new URL(url).pathname
  if (path === '/account/refresh') return Response.json({ access_token: 'fixture' })
  if (path === '/account/me') return Response.json({ id: 'fixture-user' })
  return Response.json({}, { status: 500 })
}

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it('shows the kit and focuses the first invalid field before submission', async () => {
  renderPath('/v2-kit')
  expect(await screen.findByRole('heading', { name: 'Component kit' })).toBeTruthy()
  fireEvent.click(screen.getAllByRole('button', { name: /^Save$/ })[0])
  expect((await screen.findByText('Enter Email.')).getAttribute('role')).toBe('alert')
  expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Email' }))
})

it('names pagination landmarks by the content they control', async () => {
  renderPath('/v2-kit')
  expect(await screen.findByRole('navigation', { name: 'Standalone example pagination' })).toBeTruthy()
  expect(screen.getByRole('navigation', { name: 'Example data table pagination' })).toBeTruthy()
})

it('loads project status and exposes a retry after the request fails', async () => {
  const fetchMock = vi.fn(async (url: string) => projectResponse(url))
  vi.stubGlobal('fetch', fetchMock)
  renderPath('/projects/95ff34eb-4d07-4a60-8669-aaf1cf5442ca/overview')
  expect(await screen.findByRole('heading', { name: 'Home' })).toBeTruthy()
  fireEvent.click(await screen.findByRole('button', { name: 'Try again' }))
  expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/status'))).toHaveLength(2)
})

it('provides a projects entry and a language control on sign-in', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({}, { status: 401 })))
  const router = renderPath('/projects')
  expect(await screen.findByRole('combobox', { name: 'Language' })).toBeTruthy()
  expect(router.state.location.pathname).toBe('/login')
})

it('switches modes through the URL and shows the selected Guided destination', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => projectResponse(url)))
  const projectId = '95ff34eb-4d07-4a60-8669-aaf1cf5442ca'
  const router = renderPath(`/projects/${projectId}/overview`)
  fireEvent.click(await screen.findByRole('button', { name: 'Guided' }))
  expect(await screen.findByRole('heading', { name: 'Describe what you want built' })).toBeTruthy()
  expect(router.state.location.pathname).toBe(`/projects/${projectId}/intake`)
  expect(screen.getByRole('button', { name: 'Guided' }).getAttribute('aria-pressed')).toBe('true')
})
