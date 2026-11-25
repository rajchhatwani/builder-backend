// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { members, projectId, root, user } from '../../../e2e/v2/fixtures/connect-a'
import { preview, previewId, previewPath } from '../../../e2e/v2/fixtures/connect-b'
import { builderFixture, id, labels, runtimeFixture } from '../../../e2e/v2/fixtures/operate-c'
import type { Screen } from '../../../e2e/v2/fixtures/operate-c'
import { entryKeys } from '../features/entry/api/entry'
import { App } from './App'
import { createAppRouter } from './router'

vi.mock('../features/guided/components/PreviewCredentials', async importOriginal => ({
  ...await importOriginal<typeof import('../features/guided/components/PreviewCredentials')>(),
  usePreviewCredentials: () => ({ credentials: { [previewId]: { token: 'preview-token', bearer: 'runtime-user', revision: 1 } }, dispatch: vi.fn() }),
}))
const data: Record<string, unknown> = {
  '/orgs': { items: [], total: 0 },
  [root]: { id: projectId, name: 'Operations workspace', version: 3 },
  [root + '/status']: { ready: true, sections: [], counts: {}, issues: [] },
  [root + '/members']: members,
  [root + '/previews']: [preview],
  [root + '/workspaces']: [],
  [root + '/spec']: { auth: { enabled: true, roles: [{ name: 'admin', label: 'Admin' }] }, entities: [] },
}
function open(path: string, override?: (url: URL, init?: RequestInit) => Response | undefined) {
  const fetcher = vi.fn(async (value: string, init?: RequestInit) => {
    const url = new URL(value)
    const response = override?.(url, init)
    if (response) return response
    if (url.pathname.startsWith(previewPath + '/')) {
      expect(init?.headers).toMatchObject({ Authorization: 'Bearer runtime-user', 'X-Preview-Token': 'preview-token' })
      expect(init?.credentials).toBe('omit')
      const payload = runtimeFixture(url.pathname.slice(previewPath.length))
      if (payload !== undefined) return Response.json(payload)
    }
    const builder = builderFixture(url.pathname, root, projectId)
    if (builder !== undefined) return Response.json(builder)
    return Object.hasOwn(data, url.pathname) ? Response.json(data[url.pathname]) :
      Response.json({ code: 'not_found', details: [] }, { status: 404 })
  })
  vi.stubGlobal('fetch', fetcher)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(entryKeys.session(), user)
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [root + '/' + path] }))
  render(<App queryClient={queryClient} router={router} />)
  return { fetcher, router }
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

for (const name of Object.keys(labels) as Screen[]) {
  it(name + ' resolves its workspace route and preview data', async () => {
    open(name)
    const [, title, marker] = labels[name]
    const main = within(await screen.findByRole('main'))
    expect(await main.findByRole('heading', { level: 1, name: title }, { timeout: 5000 })).toBeTruthy()
    if (name === 'routing') {
      fireEvent.change(await main.findByLabelText('Address', { exact: true }), { target: { value: 'Central warehouse' } })
      fireEvent.click(main.getAllByRole('button', { name: 'Geocode' })[0])
      expect(await main.findByText(marker, { exact: true })).toBeTruthy()
    } else if (name === 'places') {
      const table = await main.findByRole('table', { name: 'Places' })
      expect(within(table).getByRole('cell', { name: marker })).toBeTruthy()
    } else {
      expect(await main.findByRole('button', { name: marker })).toBeTruthy()
    }
  })
}

it('sends acknowledgement names from the document conflict response', async () => {
  const path = previewPath + '/ai/documents/' + id + '/approve'
  const { fetcher } = open('documents', (url, init) => {
    if (url.pathname !== path) return
    return init?.body ? Response.json({ ...runtimeFixture('/ai/documents/' + id) as object, status: 'approved' }) :
      Response.json({ code: 'review_pending', details: [{ name: 'total' }] }, { status: 409 })
  })
  fireEvent.click(await screen.findByRole('button', { name: 'Reviewed invoice' }))
  expect(await screen.findByText('54', { selector: 'mark' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Acknowledge and approve' }))
  await waitFor(() => expect(fetcher.mock.calls.find(([url, init]) => url.endsWith(path) && init?.body)?.[1]?.body)
    .toBe(JSON.stringify({ acknowledge: ['total'] })))
})

it('loads the Builder PDF editor without preview credentials and preserves the draft on conflict', async () => {
  const path = root + '/documents'
  const { fetcher } = open('documents?tab=pdf', (url, init) => url.pathname === path && init?.method === 'PUT'
    ? Response.json({ code: 'conflict', message: 'The settings changed.', details: [] }, { status: 409 }) : undefined)
  const table = await screen.findByRole('table', { name: 'Your templates' })
  expect(within(table).getByRole('cell', { name: 'Invoice template' })).toBeTruthy()
  const rate = await screen.findByLabelText('Rate limit per client')
  await waitFor(() => expect((rate as HTMLInputElement).disabled).toBe(false))
  fireEvent.change(rate, { target: { value: '40/minute' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByText('Someone else saved these document settings.', { exact: false })).toBeTruthy()
  expect((rate as HTMLInputElement).value).toBe('40/minute')
  const write = fetcher.mock.calls.find(([url, init]) => url.endsWith(path) && init?.method === 'PUT')
  expect(JSON.parse(String(write?.[1]?.body))).toMatchObject({ expected_version: 3, rate_limit: '40/minute' })
  expect(fetcher.mock.calls.some(([url]) => url.includes(previewPath + '/ai/documents'))).toBe(false)
})

it('gives Builder viewers access to prediction records without write actions', async () => {
  open('prediction', url => url.pathname === root + '/members'
    ? Response.json(members.map(member => member.user_id === user.id ? { ...member, role: 'viewer' } : member)) : undefined)
  expect(await screen.findByRole('button', { name: 'Trip 21' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Predict and record' })).toBeNull()
})
