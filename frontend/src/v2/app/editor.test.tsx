// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { openInEditor } from '../patterns/editorLink'
import { App } from './App'
import { createAppRouter } from './router'

vi.mock('../features/editor/components/MonacoSurface', () => ({
  default: ({ value, path, readOnly, onChange }: { value: string; path: string; readOnly: boolean; onChange: (value: string) => void }) =>
    <textarea aria-label={path} value={value} readOnly={readOnly} onChange={event => onChange(event.target.value)} />,
}))

const project = 'test-project'
const params = { projectId: project, workspace: 'draft', path: 'app/hooks.py' }
const sha = '1'.repeat(64)
const entries = [
  { path: 'app/hooks.py', size: 6, editable: true, zone: 'custom' },
  { path: 'main.py', size: 10, editable: false, zone: 'generated' },
]
const response = (content: string, hash = sha) => ({ ...entries[0], content, sha256: hash })

function setup(path: string, handler: (url: URL, init?: RequestInit) => Response | undefined, role = 'owner') {
  const request = vi.fn(async (address: string, init?: RequestInit) => {
    const url = new URL(address)
    if (url.pathname.endsWith('/status')) return Response.json({
      ready: true, sections: [], counts: {}, issues: [],
      next_step: { id: 'generate', section: 'generate', title: 'Generate your backend', reason: 'The model is valid.' },
    })
    if (url.pathname === '/account/me') return Response.json({ id: 'me' })
    if (url.pathname.endsWith('/members')) return Response.json([{ user_id: 'me', role }])
    if (url.pathname.endsWith('/workspaces')) return Response.json([{ id: 'draft', name: 'Draft', state: 'active' }])
    return handler(url, init) ?? Response.json({}, { status: 404 })
  })
  vi.stubGlobal('fetch', request)
  const client = new QueryClient()
  const router = createAppRouter(client, createMemoryHistory({ initialEntries: ['/projects/' + project + '/' + path] }))
  render(<App queryClient={client} router={router} />)
  return { request, router }
}

beforeEach(() => {
  localStorage.setItem('v2-language', 'en')
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it('opens deep links and searches paths and previously loaded workspace content', async () => {
  const { router } = setup('code?workspace=draft&file=app%2Fhooks.py', url => {
    if (url.pathname.endsWith('/files')) return Response.json(entries)
    if (url.searchParams.get('path') === 'app/hooks.py') return Response.json(response('custom\nneedle'))
    if (url.searchParams.get('path') === 'main.py') return Response.json({ ...entries[1], content: 'generated', sha256: sha })
  })
  expect(await screen.findByRole('textbox', { name: 'app/hooks.py' })).toHaveProperty('value', 'custom\nneedle')
  expect(screen.getByRole('navigation', { name: 'Breadcrumb' })).toBeTruthy()
  expect(screen.getByRole('navigation', { name: 'File path' }).textContent).toBe('app/hooks.py')
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Files' })).getByRole('button', { name: /main.py/ }))
  expect(await screen.findByRole('textbox', { name: 'main.py' })).toHaveProperty('readOnly', true)
  fireEvent.click(screen.getByRole('button', { name: 'Search across files' }))
  fireEvent.change(await screen.findByRole('searchbox'), { target: { value: 'needle' } })
  fireEvent.click(await screen.findByRole('button', { name: /app\/hooks.py · line 2/ }))
  expect(await screen.findByRole('textbox', { name: 'app/hooks.py' })).toBeTruthy()
  expect(router.state.location.search).toMatchObject({ file: 'app/hooks.py', line: 2 })
  expect(router.buildLocation(openInEditor(params)).search).toMatchObject({ workspace: 'draft', file: 'app/hooks.py' })
})

it('preserves a changed draft on 409 and reloads only after confirmation', async () => {
  let stale = false
  const { request } = setup('code?workspace=draft&file=app%2Fhooks.py', (url, init) => {
    if (url.pathname.endsWith('/files')) return Response.json(entries)
    if (init?.method === 'PUT') {
      stale = true
      return Response.json({ code: 'file_changed', message: 'the file changed since it was opened', details: [] }, { status: 409 })
    }
    return Response.json(stale ? response('latest', '2'.repeat(64)) : response('original'))
  })
  const editor = await screen.findByRole('textbox', { name: 'app/hooks.py' })
  const save = await screen.findByRole('button', { name: 'Save' })
  fireEvent.change(editor, { target: { value: 'my draft' } })
  fireEvent.click(save)
  expect(await screen.findByText(/The file changed since you opened it/)).toBeTruthy()
  expect(editor).toHaveProperty('value', 'my draft')
  const write = request.mock.calls.find(([, init]) => init?.method === 'PUT')
  expect(JSON.parse(String(write?.[1]?.body))).toEqual({ path: 'app/hooks.py', content: 'my draft', expected_sha256: sha })
  fireEvent.click(screen.getByRole('button', { name: 'Reload latest' }))
  const dialog = await screen.findByRole('dialog', { name: 'Discard unsaved changes?' })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Discard changes' }))
  expect(await screen.findByDisplayValue('latest')).toBeTruthy()
})

it('keeps viewers read-only for custom-zone files', async () => {
  setup('code?workspace=draft&file=app%2Fhooks.py', url => Response.json(url.pathname.endsWith('/files') ? entries : response('original')), 'viewer')
  expect(await screen.findByRole('textbox', { name: 'app/hooks.py' })).toHaveProperty('readOnly', true)
  expect(screen.getByText('Read-only', { exact: true })).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
})

it('moves Generate preview into the file manifest without downloading a zip', async () => {
  const { request } = setup('generate', url => {
    if (url.pathname.endsWith('/generate/preview')) {
      return Response.json({ files: [{ path: 'main.py', size: 10 }], spec_hash: 'spec', total_files: 1, total_size: 10 })
    }
  })
  fireEvent.click(await screen.findByRole('link', { name: 'Preview files' }))
  expect(await screen.findByText('10 bytes')).toBeTruthy()
  expect(request.mock.calls.some(([url]) => url.includes('/generate/download'))).toBe(false)
})

it('keeps the edit if the user cancels navigation, and discards it when confirmed', async () => {
  const { router } = setup('code?workspace=draft&file=app%2Fhooks.py', url => {
    if (url.pathname.endsWith('/files')) return Response.json(entries)
    return Response.json(response('original'))
  })
  const editor = await screen.findByRole('textbox', { name: 'app/hooks.py' })
  await screen.findByRole('button', { name: 'Save' })
  fireEvent.change(editor, { target: { value: 'keep this' } })
  const dashboard = screen.getByRole('link', { name: 'Open the dashboard sections' })
  fireEvent.click(dashboard)
  const dialog = await screen.findByRole('dialog')
  fireEvent.keyDown(dialog, { key: 'Escape' })
  expect(editor).toHaveProperty('value', 'keep this')
  fireEvent.click(dashboard)
  const nextDialog = await screen.findByRole('dialog')
  fireEvent.click(within(nextDialog).getByRole('button', { name: 'Discard changes' }))
  await screen.findByRole('heading', { name: 'Home' })
  expect(router.state.location.pathname).toBe('/projects/' + project + '/overview')
})

it('saves a custom file with Ctrl+S and updates the baseline for the next edit', async () => {
  const nextSha = '2'.repeat(64)
  let current = response('original')
  const writes: string[] = []
  setup('code?workspace=draft&file=app%2Fhooks.py', (url, init) => {
    if (url.pathname.endsWith('/files')) return Response.json(entries)
    if (init?.method === 'PUT') {
      const { expected_sha256, content } = JSON.parse(String(init.body))
      writes.push(expected_sha256)
      current = response(content, nextSha)
    }
    return Response.json(current)
  })
  const editor = await screen.findByRole('textbox', { name: 'app/hooks.py' })
  await screen.findByRole('button', { name: 'Save' })
  fireEvent.change(editor, { target: { value: 'first edit' } })
  fireEvent.keyDown(editor, { ctrlKey: true, key: 's' })
  expect(await screen.findByText('Saved', { exact: true })).toBeTruthy()
  fireEvent.change(editor, { target: { value: 'second edit' } })
  fireEvent.keyDown(editor, { ctrlKey: true, key: 's' })
  expect(await screen.findByText('Saved', { exact: true })).toBeTruthy()
  expect(writes).toEqual([sha, nextSha])
})
