// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { members, projectId, root, user } from '../../../e2e/v2/fixtures/connect-a'
import { created, deployment, generationId, migration, paged, patch, proposal, proposalId, shipFixture } from '../../../e2e/v2/fixtures/ship'
import { entryKeys } from '../features/entry/api/entry'
import { App } from './App'
import { createAppRouter } from './router'

function open(path: string, override?: (path: string, init?: RequestInit, url?: URL) => Response | undefined, role = 'owner') {
  const shared: Record<string, unknown> = {
    '/orgs': { items: [], total: 0 }, '/account/me': user,
    [root]: { id: projectId, name: 'Warehouse', slug: 'warehouse', version: 3 },
    [root + '/status']: { ready: true, sections: [], counts: {}, issues: [] },
    [root + '/members']: members.map(member => member.user_id === user.id ? { ...member, role } : member),
  }
  const fetcher = vi.fn(async (value: string, init?: RequestInit) => {
    const url = new URL(value)
    if (Object.hasOwn(shared, url.pathname)) return Response.json(shared[url.pathname])
    const endpoint = url.pathname.startsWith(root) ? url.pathname.slice(root.length) : url.pathname.replace('/generations/', '/generation/')
    return override?.(endpoint, init, url) ?? (Object.hasOwn(shipFixture, endpoint)
      ? Response.json(shipFixture[endpoint]) : Response.json({ code: 'not_found', details: [] }, { status: 404 }))
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
  vi.restoreAllMocks()
})

it('validates deployment fields and retains a stale draft until a successful reload', async () => {
  let serverVersion = deployment.version
  const { fetcher } = open('deployment', (path, init) => {
    if (path !== '/deployment') return
    if (init?.method === 'PUT') {
      serverVersion += 1
      return Response.json({ code: 'stale_version', details: [] }, { status: 409 })
    }
    return Response.json({ ...deployment, version: serverVersion })
  })
  const region = await screen.findByLabelText('Region', {}, { timeout: 5000 }) as HTMLInputElement
  fireEvent.change(region, { target: { value: 'wrong' } })
  fireEvent.blur(region)
  expect(await screen.findByText('Enter a region in the cloud’s format, for example eu-west-1.')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(fetcher.mock.calls.some(([, init]) => init?.method === 'PUT')).toBe(false)
  fireEvent.change(region, { target: { value: 'ap-south-1' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  const conflict = await screen.findByTestId('conflict')
  expect(region.value).toBe('ap-south-1')
  const put = fetcher.mock.calls.find(([, init]) => init?.method === 'PUT')
  expect(JSON.parse(String(put?.[1]?.body))).toMatchObject({ expected_version: 3, region: 'ap-south-1' })
  fireEvent.click(within(conflict).getByRole('button', { name: 'Reload' }))
  await waitFor(() => expect(region.value).toBe('eu-west-1'))
})

it('previews generated files without recording a download and opens paged history details', async () => {
  const { fetcher } = open('generate?page=2&generation=' + generationId)
  const preview = await screen.findByRole('button', { name: 'Preview files' }, { timeout: 5000 })
  await waitFor(() => expect(preview.hasAttribute('disabled')).toBe(false))
  fireEvent.click(preview)
  const file = await screen.findByRole('link', { name: 'Open app/main.py in the editor' })
  expect(file.getAttribute('href')).toContain('/code?file=app%2Fmain.py')
  expect(await screen.findByRole('table', { name: 'File manifest' })).toBeTruthy()
  expect(fetcher.mock.calls.some(([url]) => url.endsWith('/generations?limit=20&offset=20'))).toBe(true)
  expect(fetcher.mock.calls.some(([url]) => url.includes('/generate/download'))).toBe(false)
})

it('shows migration steps on download refusal without granting the viewer an override', async () => {
  const { fetcher } = open('generate', path => path === '/generate/download'
    ? Response.json({ code: 'destructive_migration', message: 'This change drops data.', details: [migration] }, { status: 409 }) : undefined, 'viewer')
  await screen.findByText('Viewers can download and read history. Check and Preview files need an editor or owner.', {}, { timeout: 5000 })
  expect(screen.getByRole('button', { name: 'Check' }).hasAttribute('disabled')).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'Download' }))
  expect(await screen.findByText('The field was removed.')).toBeTruthy()
  expect(screen.getByText('Only an editor or owner can allow a destructive migration.')).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Review destructive download' })).toBeNull()
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/generate/download')).length).toBe(1)
})

it('reads a proposal and refreshes it and the list after a confirmed decision', async () => {
  let dismissed = false
  open('upgrades?proposal=' + proposalId, (path, init) => {
    if (path.endsWith('/patch')) return new Response(patch)
    if (path.endsWith('/dismiss') && init?.method === 'POST') dismissed = true
    if (!dismissed) return
    const closed = { ...proposal, status: 'dismissed', decided_at: created }
    if (path === '/upgrades') return Response.json(paged([closed]))
    if (path.startsWith('/upgrades/')) return Response.json(closed)
  })
  expect(await screen.findByTestId('score', {}, { timeout: 5000 })).toBeTruthy()
  expect((await screen.findByTestId('patch')).textContent).toContain('+++ b/app/main.py')
  fireEvent.click(await screen.findByTestId('dismiss'))
  expect(within(await screen.findByRole('dialog')).getByText('You can create a new one later.')).toBeTruthy()
  fireEvent.click(screen.getByTestId('confirm-decide'))
  await waitFor(() => expect(screen.getByTestId('proposal-status').textContent).toBe('Dismissed'))
  expect(screen.getByTestId('closed-note').textContent).toContain('Dismissed')
})

it('requires two separate acknowledgements and preserves attachment provenance', async () => {
  const downloads: URLSearchParams[] = []
  const attachments: string[] = []
  vi.stubGlobal('URL', class extends URL {
    static createObjectURL() { return 'blob:ship-test' }
    static revokeObjectURL() {}
  })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    attachments.push(this.download)
  })
  open('generate', (path, _init, url) => {
    if (path === '/auth') return Response.json({ enabled: true, provider: 'builtin', jwt_algorithm: 'HS256' })
    if (path !== '/generate/download' || !url) return
    downloads.push(url.searchParams)
    if (!url.searchParams.has('accept_unreadable_baseline')) {
      return Response.json({ code: 'migration_baseline_unreadable', message: 'The baseline is unreadable.', details: [{ generation_id: generationId }] }, { status: 409 })
    }
    if (!url.searchParams.has('allow_destructive')) {
      return Response.json({ code: 'destructive_migration', message: 'This change drops data.', details: [migration] }, { status: 409 })
    }
    return new Response('zip', { headers: {
      'Content-Disposition': 'attachment; filename="server.zip"', 'X-Generation-Id': generationId, 'X-Spec-Hash': migration.new_spec_hash,
    } })
  })
  fireEvent.click(await screen.findByRole('button', { name: 'Download' }, { timeout: 5000 }))
  fireEvent.click(await screen.findByRole('button', { name: 'Review without a baseline' }))
  fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Accept unreadable baseline' }))
  expect(await screen.findByText('The field was removed.')).toBeTruthy()
  expect(attachments).toEqual([])
  fireEvent.click(screen.getByRole('button', { name: 'Review destructive download' }))
  fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Allow destructive download' }))
  expect(await screen.findByRole('heading', { name: 'Before you run warehouse' })).toBeTruthy()
  expect(screen.getByText('AUTH_JWT_SECRET', { exact: true })).toBeTruthy()
  expect(attachments).toEqual(['server.zip'])
  expect(downloads.map(query => Object.fromEntries(query))).toEqual([
    {}, { accept_unreadable_baseline: 'true' }, { accept_unreadable_baseline: 'true', allow_destructive: 'true' },
  ])
})

it('refreshes the email on a generation verification refusal and offers resend with a cooldown', async () => {
  const { fetcher } = open('generate', path => {
    if (path === '/generate/self-host-kit') {
      return Response.json({ code: 'email_not_verified', details: [] }, { status: 403 })
    }
    if (path === '/account/verify-email/resend') return Response.json({ status: 'sent' })
  })
  fireEvent.click(await screen.findByTestId('self-host-kit', {}, { timeout: 5000 }))
  fireEvent.click(await screen.findByTestId('resend'))
  expect(await screen.findByTestId('resend-note')).toBeTruthy()
  expect(screen.getByTestId('resend')).toHaveProperty('disabled', true)
  const resend = fetcher.mock.calls.find(([url]) => url.endsWith('/account/verify-email/resend'))
  expect(JSON.parse(String(resend?.[1]?.body))).toEqual({ email: user.email })
})
