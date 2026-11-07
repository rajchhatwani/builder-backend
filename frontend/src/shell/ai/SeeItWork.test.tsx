import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { SeeItWork } from './SeeItWork'
import { forgetTokens } from './seeItLogic'

const m = vi.hoisted(() => ({ listPreviews: vi.fn(), createPreview: vi.fn(), getPreview: vi.fn(), rotatePreviewToken: vi.fn() }))
vi.mock('./aiApi', () => ({ aiApi: m }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const pv = (state: string, extra = {}) => ({ id: 'pv1', project_id: 'p', workspace_id: null, state, spec_hash: 'h', url_path: '/previews/pv1/', error: null, created_at: '', last_request_at: '', expires_at: '', limits: {}, is_preview: true, ...extra })
const doc = {
  paths: {
    '/posts': { get: {}, post: { requestBody: { content: { 'application/json': { schema: { type: 'object', required: ['title'], properties: { title: { type: 'string', minLength: 12 } } } } } } } },
    '/posts/{item_id}': { parameters: [{ name: 'item_id', in: 'path', required: true, schema: { type: 'string' } }], get: {}, patch: {} },
  },
}
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })
function api(over: Record<string, (init: RequestInit) => Response> = {}) {
  return vi.fn(async (url: string, init: RequestInit) => {
    const u = new URL(url).pathname.replace('/previews/pv1', '')
    const key = `${init.method} ${u}`
    if (over[key]) return over[key](init)
    if (key === 'GET /openapi.json') return json(doc)
    if (key === 'GET /posts') return json({ items: [] })
    if (key === 'POST /posts') return json({ id: '9', title: 'preview-data' }, 201)
    if (key === 'GET /posts/9') return json({ id: '9' })
    if (key === 'PATCH /posts/9') return json({ id: '9' })
    return json({}, 404)
  })
}

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
afterEach(() => { act(() => root?.unmount()); host?.remove(); Object.values(m).forEach((f) => f.mockReset()); forgetTokens() })
async function mount(f: ReturnType<typeof api>) {
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
  await act(async () => { root!.render(createElement(SeeItWork, { projectId: 'p', pollMs: 1, readyTimeoutMs: 200, fetchImpl: f as never })) })
}
const q = (id: string) => host.querySelector(`[data-testid=${id}]`)
const click = async (el: Element | null) => { await act(async () => { (el as HTMLElement).click(); await new Promise((r) => setTimeout(r, 20)) }) }

describe('See it work', () => {
  it('starts a preview, waits for ready, lists endpoints and passes all four checks', async () => {
    m.listPreviews.mockResolvedValue([])
    m.createPreview.mockResolvedValue({ ...pv('starting'), token: 'tok_secret' })
    m.getPreview.mockResolvedValueOnce(pv('starting')).mockResolvedValue(pv('running'))
    const f = api()
    await mount(f)
    expect(q('seeit-run-all')).toHaveProperty('disabled', true)
    await click(q('seeit-start'))
    expect(q('seeit-verdict-preview')?.textContent).toBe('Pass')
    expect(q('seeit-verdict-endpoints')?.textContent).toBe('Pass')
    expect(q('seeit-ep-posts-create')?.textContent).toContain('POST /posts')
    expect((f.mock.calls[0]![1].headers as Record<string, string>)['X-Preview-Token']).toBe('tok_secret')
    await click(q('seeit-run-all'))
    for (const s of ['list', 'create', 'read', 'update']) expect(q(`seeit-verdict-${s}`)?.textContent).toBe('Pass')
    expect(q('seeit-acceptance')?.getAttribute('data-accepted')).toBe('true')
    expect(host.textContent).not.toContain('tok_secret')
    const createBody = JSON.parse(String(f.mock.calls.find((c) => c[1].method === 'POST')![1].body))
    expect(createBody.title).toBe('preview-data')
  })
  it('marks a failing step with the evidence and stops there', async () => {
    m.listPreviews.mockResolvedValue([])
    m.createPreview.mockResolvedValue({ ...pv('running'), token: 'tk' })
    const f = api({ 'POST /posts': () => json({ code: 'validation_error' }, 422) })
    await mount(f)
    await click(q('seeit-start'))
    await click(q('seeit-run-all'))
    expect(q('seeit-verdict-list')?.textContent).toBe('Pass')
    expect(q('seeit-verdict-create')?.textContent).toBe('Fail')
    expect(q('seeit-evidence-create')?.textContent).toContain('422')
    expect(q('seeit-verdict-read')?.textContent).toBe('Not yet')
    expect(q('seeit-acceptance')?.getAttribute('data-accepted')).toBe('false')
  })
  it('shows the server message when the preview is refused', async () => {
    m.listPreviews.mockResolvedValue([])
    m.createPreview.mockRejectedValue(new ApiError(403, { code: 'email_not_verified', message: 'confirm your e-mail address first', details: [] }))
    await mount(api())
    await click(q('seeit-start'))
    expect(q('seeit-error')?.textContent).toContain('confirm your e-mail address first')
    expect(q('seeit-verdict-preview')?.textContent).toBe('Fail')
  })
  it('offers a new token when the live-preview quota is hit', async () => {
    m.listPreviews.mockResolvedValue([pv('running')])
    m.createPreview.mockRejectedValue(new ApiError(409, { code: 'preview_quota', message: 'you already have 1 live preview(s)', details: [] }))
    m.rotatePreviewToken.mockResolvedValue({ ...pv('running'), token: 'tk2' })
    await mount(api())
    await click(q('seeit-start'))
    await click(q('seeit-rotate'))
    expect(m.rotatePreviewToken).toHaveBeenCalledWith('p', 'pv1')
    expect(q('seeit-verdict-endpoints')?.textContent).toBe('Pass')
  })
  it('reports a preview that failed to start', async () => {
    m.listPreviews.mockResolvedValue([])
    m.createPreview.mockResolvedValue({ ...pv('starting'), token: 'tk' })
    m.getPreview.mockResolvedValue(pv('failed', { error: 'start timed out' }))
    await mount(api())
    await click(q('seeit-start'))
    expect(q('seeit-error')?.textContent).toContain('start timed out')
  })
})
