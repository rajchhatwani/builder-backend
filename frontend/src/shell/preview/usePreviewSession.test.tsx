import { act, createElement, useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flush, mount, unmount } from '../ai/testUtils'

const listPreviews = vi.fn()
const createPreview = vi.fn()
const rotatePreviewToken = vi.fn()
vi.mock('../../api/client', () => ({ api: { listPreviews: (...a: unknown[]) => listPreviews(...a), createPreview: (...a: unknown[]) => createPreview(...a), rotatePreviewToken: (...a: unknown[]) => rotatePreviewToken(...a) } }))

import { usePreviewSession } from './usePreviewSession'
import type { PreviewSession } from './previewSession'

const ORIGIN = 'http://gen.test'
const pv = (id: string, state: string, created = '2026-01-01T00:00:00Z') => ({ id, state, created_at: created, url_path: `/previews/${id}/` })
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })

interface Seen { url: string; method: string; headers: Record<string, string>; body?: string }
function fakeFetch(handler: (s: Seen) => Response | Promise<Response>) {
  const seen: Seen[] = []
  const f = (async (url: string, init: RequestInit) => {
    const s = { url, method: init.method ?? 'GET', headers: init.headers as Record<string, string>, body: init.body as string | undefined }
    seen.push(s)
    return handler(s)
  }) as unknown as typeof fetch
  return { f, seen }
}
const okLogin = (s: Seen) => (s.url.endsWith('/auth/login') ? json({ access_token: 'JWT1' }) : json({ ok: true }))

let cur: PreviewSession
function Probe(p: { projectId: string; origin?: string | null; doFetch?: typeof fetch; pollMs?: number }) {
  cur = usePreviewSession(p.projectId, { origin: p.origin === undefined ? ORIGIN : p.origin, doFetch: p.doFetch, pollMs: p.pollMs ?? 5 })
  return createElement('span', null, cur.status)
}
const waitFor = async (cond: () => boolean) => {
  for (let i = 0; i < 200 && !cond(); i++) await act(async () => { await new Promise((r) => setTimeout(r, 5)) })
  expect(cond()).toBe(true)
}

beforeEach(() => {
  listPreviews.mockReset(); createPreview.mockReset(); rotatePreviewToken.mockReset()
  rotatePreviewToken.mockResolvedValue({ token: 'PT1' })
})

describe('usePreviewSession', () => {
  it('reports no-origin without calling the platform', async () => {
    await mount(createElement(Probe, { projectId: 'p', origin: null }))
    expect(cur.status).toBe('no-origin')
    expect(listPreviews).not.toHaveBeenCalled()
  })
  it('reports no-preview when the project has none', async () => {
    listPreviews.mockResolvedValue([pv('a', 'expired')])
    await mount(createElement(Probe, { projectId: 'p' }))
    expect(cur.status).toBe('no-preview')
    expect(cur.base).toBeNull()
  })
  it('rotates the token once for a running preview and asks to sign in', async () => {
    listPreviews.mockResolvedValue([pv('a', 'running')])
    await mount(createElement(Probe, { projectId: 'p' }))
    expect(cur.status).toBe('needs-signin')
    expect(cur.base).toBe('http://gen.test/previews/a')
    expect(rotatePreviewToken).toHaveBeenCalledTimes(1)
    expect(rotatePreviewToken).toHaveBeenCalledWith('p', 'a')
  })
  it('picks a sleeping preview', async () => {
    listPreviews.mockResolvedValue([pv('z', 'sleeping')])
    await mount(createElement(Probe, { projectId: 'p' }))
    expect(cur.status).toBe('needs-signin')
    expect(cur.previewState).toBe('sleeping')
  })
  it('polls a starting preview until it runs', async () => {
    let n = 0
    listPreviews.mockImplementation(async () => [pv('a', ++n < 3 ? 'starting' : 'running')])
    await mount(createElement(Probe, { projectId: 'p' }))
    await waitFor(() => cur.status === 'needs-signin')
    expect(n).toBe(3)
    expect(rotatePreviewToken).toHaveBeenCalledTimes(1)
  })
  it('shows an error status when the platform call fails', async () => {
    listPreviews.mockRejectedValue(new Error('down'))
    await mount(createElement(Probe, { projectId: 'p' }))
    expect(cur.status).toBe('error')
    expect(cur.error).toBe('down')
  })

  it('signs in, becomes ready and sends both headers afterwards', async () => {
    listPreviews.mockResolvedValue([pv('a', 'running')])
    const { f, seen } = fakeFetch(okLogin)
    await mount(createElement(Probe, { projectId: 'p', doFetch: f }))
    let msg: string | null = 'x'
    await act(async () => { msg = await cur.signIn('e@x.test', 'pw') })
    expect(msg).toBeNull()
    expect(cur.status).toBe('ready')
    expect(seen[0].url).toBe('http://gen.test/previews/a/auth/login')
    expect(seen[0].headers['X-Preview-Token']).toBe('PT1')
    expect(seen[0].headers.Authorization).toBeUndefined()
    await act(async () => { await cur.request('GET', '/things') })
    const last = seen[seen.length - 1]
    expect(last.url).toBe('http://gen.test/previews/a/things')
    expect(last.headers['X-Preview-Token']).toBe('PT1')
    expect(last.headers.Authorization).toBe('Bearer JWT1')
  })
  it('returns a readable message for a failed sign-in', async () => {
    listPreviews.mockResolvedValue([pv('a', 'running')])
    const { f } = fakeFetch(() => json({ detail: 'Bad credentials' }, 400))
    await mount(createElement(Probe, { projectId: 'p', doFetch: f }))
    let msg: string | null = null
    await act(async () => { msg = await cur.signIn('e', 'pw') })
    expect(msg).toBe('Bad credentials')
    expect(cur.status).toBe('needs-signin')
  })
  it('register creates the account then signs in', async () => {
    listPreviews.mockResolvedValue([pv('a', 'running')])
    const { f, seen } = fakeFetch(okLogin)
    await mount(createElement(Probe, { projectId: 'p', doFetch: f }))
    let msg: string | null = 'x'
    await act(async () => { msg = await cur.register('e@x.test', 'password1') })
    expect(msg).toBeNull()
    expect(seen.map((s) => s.url.split('/').pop())).toEqual(['register', 'login'])
    expect(cur.status).toBe('ready')
  })

  it('a 401 about the preview token drops tokens and reconnects', async () => {
    listPreviews.mockResolvedValue([pv('a', 'running')])
    rotatePreviewToken.mockResolvedValueOnce({ token: 'PT1' }).mockResolvedValueOnce({ token: 'PT2' })
    const { f, seen } = fakeFetch((s) => (s.url.endsWith('/things') ? json({ detail: 'Invalid preview token' }, 401) : okLogin(s)))
    await mount(createElement(Probe, { projectId: 'p', doFetch: f }))
    await act(async () => { await cur.signIn('e', 'pw') })
    await act(async () => { await cur.request('GET', '/things') })
    await waitFor(() => rotatePreviewToken.mock.calls.length === 2)
    await waitFor(() => cur.status === 'needs-signin')
    await act(async () => { await cur.request('GET', '/other') })
    const last = seen[seen.length - 1]
    expect(last.headers['X-Preview-Token']).toBe('PT2')
    expect(last.headers.Authorization).toBeUndefined()
  })
  it('any other 401 returns to needs-signin', async () => {
    listPreviews.mockResolvedValue([pv('a', 'running')])
    const { f } = fakeFetch((s) => (s.url.endsWith('/things') ? json({ detail: 'Token expired' }, 401) : okLogin(s)))
    await mount(createElement(Probe, { projectId: 'p', doFetch: f }))
    await act(async () => { await cur.signIn('e', 'pw') })
    expect(cur.status).toBe('ready')
    await act(async () => { await cur.request('GET', '/things') })
    expect(cur.status).toBe('needs-signin')
    expect(rotatePreviewToken).toHaveBeenCalledTimes(1)
  })

  it('start() creates a preview then connects', async () => {
    listPreviews.mockResolvedValueOnce([]).mockResolvedValue([pv('n', 'running')])
    createPreview.mockResolvedValue({ ...pv('n', 'starting'), token: 'PTN' })
    await mount(createElement(Probe, { projectId: 'p' }))
    expect(cur.status).toBe('no-preview')
    await act(async () => { await cur.start() })
    expect(createPreview).toHaveBeenCalledWith('p')
    expect(cur.status).toBe('needs-signin')
    expect(cur.base).toBe('http://gen.test/previews/n')
    expect(rotatePreviewToken).not.toHaveBeenCalled() // the created token is reused
  })

  it('changing projectId clears tokens', async () => {
    listPreviews.mockImplementation(async (id: string) => [pv(id === 'p1' ? 'a' : 'b', 'running')])
    const { f, seen } = fakeFetch(okLogin)
    let setId: (id: string) => void = () => {}
    function Switch() { const [id, set] = useState('p1'); setId = set; return createElement(Probe, { projectId: id, doFetch: f }) }
    await mount(createElement(Switch))
    await act(async () => { await cur.signIn('e', 'pw') })
    expect(cur.status).toBe('ready')
    await act(async () => { setId('p2') })
    await waitFor(() => cur.status === 'needs-signin' && cur.base === 'http://gen.test/previews/b')
    await act(async () => { await cur.request('GET', '/x') })
    expect(seen[seen.length - 1].url).toBe('http://gen.test/previews/b/x')
    expect(seen[seen.length - 1].headers.Authorization).toBeUndefined()
  })

  it('unmount stops polling', async () => {
    listPreviews.mockResolvedValue([pv('a', 'starting')])
    await mount(createElement(Probe, { projectId: 'p', pollMs: 5 }))
    await waitFor(() => listPreviews.mock.calls.length >= 3)
    unmount()
    await flush()
    const n = listPreviews.mock.calls.length
    await act(async () => { await new Promise((r) => setTimeout(r, 60)) })
    expect(listPreviews.mock.calls.length).toBeLessThanOrEqual(n + 1)
  })
})
