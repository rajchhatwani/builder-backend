import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { CodeView } from './CodeView'
import { DataBrowser } from './DataBrowser'
import { RunLogs } from './RunLogs'

const m = vi.hoisted(() => ({ list: vi.fn(), read: vi.fn(), write: vi.fn() }))
vi.mock('./workspaceApi', () => ({ workspaceApi: m }))
// The real editor needs a browser; stand in with a textarea that keeps the same props contract.
vi.mock('./MonacoEditor', () => ({
  default: (p: { value: string; readOnly: boolean; onChange: (v: string) => void; onSave: () => void }) =>
    createElement('textarea', { 'data-testid': 'fake-editor', value: p.value, readOnly: p.readOnly, onChange: (e: { target: { value: string } }) => p.onChange(e.target.value), onKeyDown: (e: { key: string; ctrlKey: boolean }) => { if (e.ctrlKey && e.key === 's') p.onSave() } }),
}))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
afterEach(() => { act(() => root?.unmount()); host?.remove(); Object.values(m).forEach((f) => f.mockReset()) })
const flush = async () => { for (let i = 0; i < 5; i++) await act(async () => { await Promise.resolve() }) }
async function mount(el: ReturnType<typeof createElement>) {
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
  await act(async () => { root!.render(el) }); await flush()
}
const q = (id: string) => host.querySelector(`[data-testid="${id}"]`) as HTMLElement | null
const click = async (el: Element | null) => { await act(async () => { (el as HTMLElement).click() }); await flush() }
const files = [
  { path: 'gen.py', zone: 'generated', size: 5, editable: false },
  { path: 'hooks/mine.py', zone: 'custom', size: 5, editable: true },
]
const content = (p: string, o = {}) => ({ path: p, zone: p === 'gen.py' ? 'generated' : 'custom', content: 'print(1)', editable: p !== 'gen.py', sha256: 'abc', ...o })

describe('CodeView', () => {
  it('shows generated files read-only with a hint and no Save', async () => {
    m.list.mockResolvedValue(files); m.read.mockResolvedValue(content('gen.py'))
    await mount(createElement(CodeView, { projectId: 'p', workspaceId: 'w' }))
    await click(q('file-gen.py'))
    expect(q('zone-generated')).toBeTruthy()
    expect(q('code-readonly-hint')?.textContent).toMatch(/edit the spec/)
    expect(q('code-save')).toBeNull()
    expect((q('fake-editor') as HTMLTextAreaElement).readOnly).toBe(true)
  })
  it('edits a custom file, marks it dirty and saves with expected_sha256', async () => {
    m.list.mockResolvedValue(files); m.read.mockResolvedValue(content('hooks/mine.py'))
    m.write.mockResolvedValue(content('hooks/mine.py', { content: 'print(2)', sha256: 'def' }))
    await mount(createElement(CodeView, { projectId: 'p', workspaceId: 'w' }))
    await click(q('file-hooks')); await click(q('file-hooks/mine.py'))
    expect(q('code-dirty')).toBeNull()
    const ta = q('fake-editor') as HTMLTextAreaElement
    await act(async () => { const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!; set.call(ta, 'print(2)'); ta.dispatchEvent(new Event('input', { bubbles: true })) })
    expect(q('code-dirty')).toBeTruthy()
    await click(q('code-save'))
    expect(m.write).toHaveBeenCalledWith('p', 'w', 'hooks/mine.py', 'print(2)', 'abc')
    expect(q('code-dirty')).toBeNull()
  })
  it('shows a conflict with a reload action on 409 file_changed', async () => {
    m.list.mockResolvedValue(files); m.read.mockResolvedValue(content('hooks/mine.py'))
    m.write.mockRejectedValue(new ApiError(409, { code: 'file_changed', message: 'x', details: [] }))
    await mount(createElement(CodeView, { projectId: 'p', workspaceId: 'w' }))
    await click(q('file-hooks')); await click(q('file-hooks/mine.py'))
    const ta = q('fake-editor') as HTMLTextAreaElement
    await act(async () => { const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!; set.call(ta, 'z'); ta.dispatchEvent(new Event('input', { bubbles: true })) })
    await click(q('code-save'))
    expect(q('code-message')?.textContent).toMatch(/changed since you opened/)
    expect(q('code-reload')).toBeTruthy()
  })
  it('shows a busy message on 409 workspace_busy', async () => {
    m.list.mockResolvedValue(files); m.read.mockResolvedValue(content('hooks/mine.py'))
    m.write.mockRejectedValue(new ApiError(409, { code: 'workspace_busy', message: 'x', details: [] }))
    await mount(createElement(CodeView, { projectId: 'p', workspaceId: 'w' }))
    await click(q('file-hooks')); await click(q('file-hooks/mine.py'))
    const ta = q('fake-editor') as HTMLTextAreaElement
    await act(async () => { const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!; set.call(ta, 'z'); ta.dispatchEvent(new Event('input', { bubbles: true })) })
    await click(q('code-save'))
    expect(q('code-message')?.textContent).toMatch(/busy/)
    expect(q('code-reload')).toBeNull()
  })
})

const sse = (text: string, status = 200) => vi.fn(async () => new Response(new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode(text)); c.close() } }), { status })) as unknown as typeof fetch
describe('RunLogs', () => {
  it('sends the token header and renders lines', async () => {
    const f = sse('event: info\ndata: hi\n\ndata: line one\n\n')
    await mount(createElement(RunLogs, { previewId: 'pv', token: 'tok', doFetch: f }))
    const call = (f as unknown as ReturnType<typeof vi.fn>).mock.calls[0]
    expect((call[1] as RequestInit).headers).toMatchObject({ 'X-Preview-Token': 'tok' })
    expect(host.querySelectorAll('[data-testid="log-line"]').length).toBe(2)
  })
  it('reports a gone preview', async () => {
    await mount(createElement(RunLogs, { previewId: 'pv', token: 'tok', doFetch: sse('', 410) }))
    expect(q('log-status')?.getAttribute('data-status')).toBe('gone')
  })
  it('asks for a token when none is set', async () => {
    await mount(createElement(RunLogs, { previewId: 'pv', token: '' }))
    expect(host.textContent).toMatch(/Add a preview token/)
  })
})

describe('DataBrowser', () => {
  it('lists entities, shows columns and pages', async () => {
    const calls: string[] = []
    const rows = Array.from({ length: 25 }, (_, i) => ({ id: i, name: `n${i}` }))
    const f = vi.fn(async (url: string) => {
      calls.push(url)
      const body = url.endsWith('/openapi.json') ? { paths: { '/invoices': { get: {} } } } : { items: rows, total: 60 }
      return new Response(JSON.stringify(body), { status: 200 })
    }) as unknown as typeof fetch
    await mount(createElement(DataBrowser, { previewId: 'pv', token: 'tok', doFetch: f }))
    expect(host.querySelectorAll('th').length).toBe(2)
    expect(host.querySelectorAll('[data-testid="data-row"]').length).toBe(25)
    expect(q('data-page')?.textContent).toBe('Page 1 of 3')
    await click(q('data-next'))
    expect(calls.some((u) => u.endsWith('/invoices?limit=25&offset=25'))).toBe(true)
  })
  it('shows an empty state', async () => {
    const f = vi.fn(async (url: string) => new Response(JSON.stringify(url.endsWith('/openapi.json') ? { paths: { '/x': { get: {} } } } : []), { status: 200 })) as unknown as typeof fetch
    await mount(createElement(DataBrowser, { previewId: 'pv', token: 'tok', doFetch: f }))
    expect(q('data-empty')).toBeTruthy()
  })
})
