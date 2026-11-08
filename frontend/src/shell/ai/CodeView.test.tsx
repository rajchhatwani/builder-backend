import { createElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { CodeView } from './CodeView'
import { click, flush, mount, q, typeInto } from './testUtils'

const m = vi.hoisted(() => ({ list: vi.fn(), read: vi.fn(), write: vi.fn() }))
vi.mock('./workspaceApi', () => ({ workspaceApi: m }))
// Stand-in for the lazy Monaco chunk with the same props contract (the real wrapper has its own test).
vi.mock('./MonacoEditor', () => ({
  default: (p: { value: string; readOnly: boolean; label: string; onChange: (v: string) => void; onSave: () => void }) =>
    createElement('textarea', { 'data-testid': 'ed', 'aria-label': p.label, value: p.value, readOnly: p.readOnly, onChange: (e: { target: { value: string } }) => p.onChange(e.target.value), onKeyDown: (e: { key: string; ctrlKey: boolean }) => { if (e.ctrlKey && e.key === 's') p.onSave() } }),
}))

const files = [
  { path: 'gen.py', zone: 'generated', size: 5, editable: false },
  { path: 'hooks/a.py', zone: 'custom', size: 5, editable: true },
  { path: 'hooks/b.py', zone: 'custom', size: 5, editable: true },
]
const body = (path: string, o = {}) => ({ path, zone: path === 'gen.py' ? 'generated' : 'custom', content: `# ${path}`, editable: path !== 'gen.py', sha256: `sha-${path}`, ...o })
const view = () => mount(createElement(CodeView, { projectId: 'p', workspaceId: 'w' }))
beforeEach(() => { Object.values(m).forEach((f) => f.mockReset()); m.list.mockResolvedValue(files); m.read.mockImplementation(async (_p, _w, path) => body(path)) })

describe('CodeView', () => {
  it('renders a nested tree that expands folders and flags read-only files', async () => {
    await view()
    expect(q('file-gen.py')?.textContent).toMatch(/gen\.py.*read-only/)
    expect(q('file-hooks/a.py')).toBeNull()
    await click(q('file-hooks'))
    expect(q('file-hooks/a.py')).toBeTruthy()
    expect(q('file-hooks')?.closest('li')?.getAttribute('aria-expanded')).toBe('true')
    expect(q('code-pick')).toBeTruthy()
  })
  it('shows an empty state and a list error with working Retry', async () => {
    m.list.mockResolvedValueOnce([])
    await view()
    expect(q('code-empty')).toBeTruthy()
  })
  it('retries a failed listing', async () => {
    m.list.mockRejectedValueOnce(new ApiError(500, { code: 'x', message: 'listing broke', details: [] }))
    await view()
    const alert = q('code-view')!.querySelector('[role="alert"]')!
    expect(alert.textContent).toMatch(/listing broke/)
    await click(alert.querySelector('button'))
    expect(q('file-gen.py')).toBeTruthy()
  })
  it('opens a file and labels the editor for assistive tech', async () => {
    await view(); await click(q('file-gen.py'))
    expect(q('code-path')?.textContent).toBe('gen.py')
    expect((q('ed') as HTMLTextAreaElement).value).toBe('# gen.py')
    expect(q('ed')?.getAttribute('aria-label')).toBe('Read-only editor for gen.py')
  })
  it('saves a dirty custom file with its sha and refreshes the list; Ctrl+S works too', async () => {
    m.write.mockResolvedValue(body('hooks/a.py', { content: 'new', sha256: 'sha2' }))
    await view(); await click(q('file-hooks')); await click(q('file-hooks/a.py'))
    expect(q('code-save')).toHaveProperty('disabled', true)
    await typeInto(q('ed') as HTMLTextAreaElement, 'new')
    expect(q('code-dirty')).toBeTruthy()
    await click(q('code-save'))
    expect(m.write).toHaveBeenCalledWith('p', 'w', 'hooks/a.py', 'new', 'sha-hooks/a.py')
    expect(q('code-message')?.textContent).toMatch(/Saved/)
    expect(q('code-dirty')).toBeNull()
    expect(m.list).toHaveBeenCalledTimes(2)
    await typeInto(q('ed') as HTMLTextAreaElement, 'newer')
    await import('react').then(({ act }) => act(async () => { q('ed')!.dispatchEvent(new KeyboardEvent('keydown', { key: 's', ctrlKey: true, bubbles: true })) }))
    expect(m.write).toHaveBeenLastCalledWith('p', 'w', 'hooks/a.py', 'newer', 'sha2')
  })
  it('keeps the draft on a save error and Reload latest re-reads the file', async () => {
    m.write.mockRejectedValue(new ApiError(409, { code: 'file_changed', message: 'x', details: [] }))
    await view(); await click(q('file-hooks')); await click(q('file-hooks/a.py'))
    await typeInto(q('ed') as HTMLTextAreaElement, 'mine')
    await click(q('code-save'))
    expect((q('ed') as HTMLTextAreaElement).value).toBe('mine')
    m.read.mockResolvedValueOnce(body('hooks/a.py', { content: 'theirs', sha256: 'new' }))
    await click(q('code-reload'))
    expect((q('ed') as HTMLTextAreaElement).value).toBe('theirs')
    expect(q('code-dirty')).toBeNull()
  })
  it('asks before discarding unsaved edits when opening another file', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    await view(); await click(q('file-hooks')); await click(q('file-hooks/a.py'))
    await typeInto(q('ed') as HTMLTextAreaElement, 'edited')
    await click(q('file-hooks/b.py'))
    expect(q('code-path')?.textContent).toBe('hooks/a.py')
    await click(q('file-hooks/b.py'))
    expect(q('code-path')?.textContent).toBe('hooks/b.py')
    expect(confirm).toHaveBeenCalledTimes(2)
    confirm.mockRestore()
  })
  it('the last file clicked wins when responses arrive out of order (S3-009)', async () => {
    const slow: Record<string, (v: unknown) => void> = {}
    m.read.mockImplementation((_p, _w, path) => new Promise((res) => { slow[path] = () => res(body(path)) }))
    await view(); await click(q('file-hooks'))
    await click(q('file-hooks/a.py')); await click(q('file-hooks/b.py'))
    slow['hooks/b.py'](null); await flush()
    slow['hooks/a.py'](null); await flush()
    expect(q('code-path')?.textContent).toBe('hooks/b.py')
  })
  it('explains binary files instead of the raw error', async () => {
    m.read.mockRejectedValue(new ApiError(415, { code: 'x', message: 'raw', details: [] }))
    await view(); await click(q('file-gen.py'))
    expect(q('code-message')?.textContent).toMatch(/binary or too large/)
  })
})
