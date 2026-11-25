// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { App } from './App'
import { createAppRouter } from './router'

const id = 'project'
const run = { id: 'run', goal: 'Build employee records', state: 'running', phase: 'build', workspace_id: 'draft',
  budgets: {}, steps_used: 0, repairs_used: 0, cost_micro_usd: 0, steps: [], steps_total: 0 }
const approval = {
  id: 'gate', run_id: run.id, kind: 'B', subject: 'Review employee records', state: 'pending', requires_owner: false,
  bound_spec_hash: 'viewed-spec', payload_hash: 'viewed-payload', bound_commit: 'viewed-commit',
  payload: { summary: 'Add an employee record.' }, risk_flags: [], expires_at: '2099-01-01T00:00:00Z', created_at: '2026-01-01T00:00:00Z',
}
const preview = { id: 'preview', project_id: id, state: 'running', workspace_id: null, is_preview: true, url_path: '/previews/preview/', limits: {} }

function open(path: string, handler: (path: string, method?: string) => unknown) {
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    const pathname = new URL(url).pathname.replace('/projects/' + id, '')
    const json = pathname === '/account/refresh' ? { access_token: 'fixture' }
      : pathname === '/account/me' ? { id: 'user', email_verified_at: '2026-01-01', platform_role: 'customer' }
      : pathname === '/members' ? [{ user_id: 'user', role: 'owner' }]
      : pathname === '/status' ? { sections: [] }
      : pathname === '/workspaces' ? []
      : pathname === '' ? { id, organization_id: null }
      : handler(pathname, init?.method)
    return Response.json(json ?? {}, { status: json == null ? 500 : 200 })
  })
  vi.stubGlobal('fetch', fetch)
  const client = new QueryClient()
  const router = createAppRouter(client, createMemoryHistory({ initialEntries: ['/projects/' + id + '/' + path] }))
  render(<App queryClient={client} router={router} />)
  return fetch
}

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it('requires confirmation before cancelling an active build', async () => {
  let cancelled = false
  const request = open('build', path => {
    if (path === '/agent/runs') return { items: [run], total: 1 }
    if (path.endsWith('/cancel')) { cancelled = true; return { ...run, state: 'cancelled' } }
    if (path === '/agent/runs/run') return { ...run, state: cancelled ? 'cancelled' : 'running' }
    if (path === '/agent/approvals') return []
  })
  fireEvent.click(await screen.findByTestId('run-cancel'))
  expect(request.mock.calls.some(([url]) => url.endsWith('/cancel'))).toBe(false)
  const dialog = await screen.findByRole('dialog', { name: 'Cancel this run?' })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel run' }))
  expect(await screen.findByText('Cancelled', { exact: true })).toBeTruthy()
})

it('reloads changed approval evidence without submitting a stale decision', async () => {
  let reads = 0
  const request = open('approvals?approval=gate', path => {
    if (path === '/agent/approvals/gate') return ++reads === 1 ? approval : {
      ...approval, bound_commit: 'new', payload: { summary: 'Changed scope.' },
    }
  })
  fireEvent.click(await screen.findByTestId('review-approve'))
  const dialog = await screen.findByRole('dialog', { name: 'Approve this request?' })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm' }))
  expect(await screen.findByText('This request changed since you opened it. Review it again before you decide.')).toBeTruthy()
  expect(screen.getByText('Changed scope.')).toBeTruthy()
  expect(request.mock.calls.some(([url]) => url.endsWith('/decision'))).toBe(false)
})

it('starts a preview and keeps its token out of navigation and storage', async () => {
  let started = false
  const request = open('see', (path, method) => {
    if (path === '/previews' && method === 'POST') {
      started = true
      return { ...preview, token: 'preview-secret' }
    }
    if (path === '/previews') return started ? [preview] : []
    if (path === '/previews/preview') return preview
    if (path.endsWith('/openapi.json')) return { paths: {} }
  })
  fireEvent.click(await screen.findByTestId('seeit-start'))
  expect(await screen.findByText('The backend describes no data endpoints.')).toBeTruthy()
  const describe = request.mock.calls.find(([url]) => url.endsWith('/openapi.json'))
  expect(new Headers(describe?.[1]?.headers).get('X-Preview-Token')).toBe('preview-secret')
  expect(screen.getByTestId('seeit-page').textContent).not.toContain('preview-secret')
  await waitFor(() => expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain('preview-secret'))
})
