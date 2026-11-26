// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { members, projectId, root, user } from '../../../e2e/v2/fixtures/connect-a'
import { preview, previewId, previewPath } from '../../../e2e/v2/fixtures/connect-b'
import { aiSpec, caller, evalId, labels, runId, runtimeFixture } from '../../../e2e/v2/fixtures/operate-d'
import { entryKeys } from '../features/entry/api/entry'
import { App } from './App'
import { createAppRouter } from './router'

vi.mock('../features/guided/components/PreviewCredentials', async importOriginal => ({
  ...await importOriginal<typeof import('../features/guided/components/PreviewCredentials')>(),
  usePreviewCredentials: () => ({ credentials: { [previewId]: { token: 'preview-token', bearer: 'runtime-user', revision: 1 } }, dispatch: vi.fn() }),
}))

function open(path: string, override?: (url: URL, init?: RequestInit) => Response | undefined, role = 'owner') {
  const builder: Record<string, unknown> = {
    '/orgs': { items: [], total: 0 },
    [root]: { id: projectId, name: 'Operations workspace', version: 3 },
    [root + '/status']: { ready: true, sections: [], counts: {}, issues: [] },
    [root + '/members']: members.map(member => member.user_id === user.id ? { ...member, role } : member),
    [root + '/previews']: [preview], [root + '/workspaces']: [], [root + '/spec']: aiSpec,
  }
  const fetcher = vi.fn(async (value: string, init?: RequestInit) => {
    const url = new URL(value)
    const response = override?.(url, init)
    if (response) return response
    if (url.pathname.startsWith(previewPath + '/')) {
      expect(init?.headers).toMatchObject({ Authorization: 'Bearer runtime-user', 'X-Preview-Token': 'preview-token' })
      expect(init?.credentials).toBe('omit')
      const payload = runtimeFixture(url.pathname.slice(previewPath.length), false, init?.method)
      if (payload !== undefined) return Response.json(payload)
    }
    return Object.hasOwn(builder, url.pathname) ? Response.json(builder[url.pathname]) :
      Response.json({ code: 'not_found', details: [] }, { status: 404 })
  })
  vi.stubGlobal('fetch', fetcher)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(entryKeys.session(), user)
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [root + '/' + path] }))
  render(<App queryClient={queryClient} router={router} />)
  return fetcher
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

it('formats the usage budget exactly and forwards URL call filters and page offset', async () => {
  const fetcher = open('aiusage?stage=support&caller=' + caller + '&status=ok&page=2')
  expect(await screen.findByRole('heading', { level: 1, name: labels.aiusage[1] }, { timeout: 5000 })).toBeTruthy()
  expect((await screen.findByTestId('usage-spent')).textContent).toBe('USD 0.250000')
  expect((await screen.findByTestId('usage-calls')).textContent).toBe('3 / 1')
  const row = await screen.findByTestId('calls-row')
  expect(row.textContent).toContain('USD 0.001234')
  const calls = new URL(fetcher.mock.calls.find(([url]) => url.includes('/ai/calls?'))![0])
  expect(Object.fromEntries(calls.searchParams)).toEqual({ limit: '50', offset: '50', stage: 'support', status: 'ok', caller_id: caller })
})

it('validates and creates a scoped knowledge source and renders returned citations as text', async () => {
  const fetcher = open('knowledge')
  expect(await screen.findByTestId('source-row', {}, { timeout: 5000 })).toBeTruthy()
  const create = await screen.findByTestId('source-create')
  fireEvent.click(create)
  expect((await screen.findByTestId('source-create-error')).textContent).toBe('Enter a title.')
  fireEvent.change(screen.getByTestId('source-title'), { target: { value: 'Policy' } })
  fireEvent.change(screen.getByTestId('source-text'), { target: { value: 'Returns are free.' } })
  const roles = screen.getByTestId('source-roles')
  act(() => roles.focus())
  fireEvent.change(roles, { target: { value: 'staff' } })
  expect(roles.getAttribute('aria-invalid')).toBe('true')
  // A focus transfer here would clear the error and move the submit button before mouseup.
  expect(fireEvent.mouseDown(create)).toBe(false)
  fireEvent.click(create)
  expect((await screen.findByTestId('source-notice')).textContent).toBe('Source added.')
  const write = fetcher.mock.calls.find(([url, init]) => url.endsWith('/ai/knowledge/sources') && init?.method === 'POST')
  expect(write?.[1]?.body).toBe(JSON.stringify({ title: 'Policy', text: 'Returns are free.', allowed_roles: ['staff'] }))
  fireEvent.change(screen.getByTestId('ask-question'), { target: { value: 'How long do refunds take?' } })
  fireEvent.change(screen.getByTestId('ask-limit'), { target: { value: '8' } })
  fireEvent.click(screen.getByTestId('ask-run'))
  const answer = await screen.findByTestId('ask-answer')
  expect(answer.textContent).toBe('<b>Five days.</b>')
  expect(answer.querySelector('b')).toBeNull()
  expect((await screen.findByTestId('ask-citation')).textContent).toContain('Refunds take five days.')
  expect(fetcher.mock.calls.find(([url]) => url.endsWith('/ai/knowledge/ask'))?.[1]?.body)
    .toBe(JSON.stringify({ question: 'How long do refunds take?', limit: 8 }))
})

it('loads a selected eval and displays the returned verdict and case error after a dry run', async () => {
  const fetcher = open('evals?suite=returns&run=' + evalId)
  expect(await screen.findByTestId('suite-row', {}, { timeout: 5000 })).toBeTruthy()
  expect((await screen.findByTestId('eval-verdict')).textContent).toBe('Suite failed')
  expect(screen.getAllByTestId('eval-case')[1].textContent).toContain('Error: budget_exceeded')
  fireEvent.click(await screen.findByTestId('suite-run'))
  expect(await screen.findByRole('heading', { name: 'Result of the run you just started' })).toBeTruthy()
  expect(fetcher.mock.calls.find(([url, init]) => url.endsWith('/ai/evals/suites/returns/run') && init?.method === 'POST')?.[1]?.body)
    .toBeUndefined()
})

it('loads generated per-agent stats and lets a viewer open run details and follow proposals', async () => {
  const fetcher = open('agentruns?statsAgent=scribe', undefined, 'viewer')
  expect(await screen.findByTestId('registry-agent', {}, { timeout: 5000 })).toBeTruthy()
  expect(await screen.findByTestId('stats-row')).toBeTruthy()
  const main = within(await screen.findByRole('main'))
  await waitFor(() => expect(main.queryByTestId('start-run')).toBeNull())
  fireEvent.click(await main.findByTestId('run-open'))
  expect((await main.findByTestId('run-status')).textContent).toBe('completed')
  expect(main.getByTestId('run-proposal').textContent).toContain('Suggested')
  expect(main.getByRole('link', { name: 'Review proposals in AI actions' }).getAttribute('href')).toContain('run=' + runId)
  expect(fetcher.mock.calls.some(([url]) => url.endsWith('/ai/agents/stats?agent=scribe'))).toBe(true)
  expect(fetcher.mock.calls.some(([url]) => url.endsWith('/ai/agents/runs/' + runId))).toBe(true)
})

it('retains the generated forbidden status and code for a read', async () => {
  open('aiusage', url => url.pathname.endsWith('/ai/usage')
    ? Response.json({ code: 'forbidden', message: 'you do not have permission to do that' }, { status: 403 }) : undefined)
  expect(await screen.findByText(/403 forbidden/, {}, { timeout: 5000 })).toBeTruthy()
})
