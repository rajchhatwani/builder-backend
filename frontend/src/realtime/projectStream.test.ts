import { describe, expect, it, vi } from 'vitest'
import { connectProjectEvents, type StreamStatus } from './projectStream'

const enc = new TextEncoder()
function streamRes(chunks: string[], status = 200, headers: Record<string, string> = {}): Response {
  const body = new ReadableStream<Uint8Array>({ start(c) { chunks.forEach((x) => c.enqueue(enc.encode(x))); c.close() } })
  return new Response(status === 200 ? body : null, { status, headers })
}
const frame = (id: number | null, type: string, data: object = {}) =>
  `${id === null ? '' : `id: ${id}\n`}event: ${type}\ndata: ${JSON.stringify({ id, topic: 't', type, data })}\n\n`

function harness(responses: Array<Response | Error>, extra: Partial<Parameters<typeof connectProjectEvents>[0]> = {}) {
  const calls: Array<{ headers: Record<string, string> }> = []
  const waits: number[] = []
  const events: Array<{ id: number | null; type: string }> = []
  const statuses: StreamStatus[] = []
  let ctlClose: () => void = () => undefined
  const doFetch = vi.fn(async (_u: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ headers: init?.headers as Record<string, string> })
    const r = responses.shift()
    if (!r) { ctlClose(); return await new Promise<Response>(() => undefined) } // park: nothing more scripted
    if (r instanceof Error) throw r
    return r
  })
  const conn = connectProjectEvents({
    projectId: 'p', doFetch: doFetch as unknown as typeof fetch, headers: () => ({ Authorization: 'Bearer t' }), refresh: async () => false,
    wait: async (ms) => { waits.push(ms) }, rand: () => 0.5, onEvent: (e) => events.push({ id: e.id, type: e.type }), onStatus: (s) => statuses.push(s), ...extra,
  })
  ctlClose = conn.close
  return { conn, calls, waits, events, statuses, doFetch }
}
const settle = () => new Promise((r) => setTimeout(r, 20))

describe('project stream', () => {
  it('delivers events (split chunks), dedupes by id, and reconnects with Last-Event-ID', async () => {
    const f = frame(1, 'spec.changed') + frame(2, 'spec.changed')
    const h = harness([streamRes([f.slice(0, 30), f.slice(30), frame(2, 'spec.changed')]), streamRes([frame(3, 'import.committed')])])
    await settle()
    expect(h.events.map((e) => e.id)).toEqual([1, 2, 3])
    expect(h.calls[0].headers['Last-Event-ID']).toBeUndefined()
    expect(h.calls[1].headers['Last-Event-ID']).toBe('2')
    expect(h.calls[1].headers.Authorization).toBe('Bearer t')
    expect(h.waits[0]).toBe(1000)
    expect(h.statuses).toContain('live')
    expect(h.statuses).toContain('reconnecting')
  })
  it('resync resets the cursor and is forwarded', async () => {
    const h = harness([streamRes([frame(50, 'spec.changed')]), streamRes([frame(4, 'resync'), frame(5, 'spec.changed')]), streamRes([])])
    await settle()
    expect(h.events.map((e) => `${e.type}:${e.id}`)).toEqual(['spec.changed:50', 'resync:4', 'spec.changed:5'])
    expect(h.calls[2].headers['Last-Event-ID']).toBe('5')
  })
  it('honours Retry-After on 429', async () => {
    const h = harness([streamRes([], 429, { 'Retry-After': '12' }), streamRes([frame(1, 'spec.changed')])])
    await settle()
    expect(h.waits[0]).toBe(12000)
    expect(h.events).toHaveLength(1)
  })
  it.each([403, 404])('stops for good on %i', async (status) => {
    const h = harness([streamRes([], status)])
    await settle()
    expect(h.doFetch).toHaveBeenCalledTimes(1)
    expect(h.statuses.at(-1)).toBe('stopped')
  })
  it('on 401 refreshes once then retries, and stops if refresh fails', async () => {
    const ok = harness([streamRes([], 401), streamRes([frame(1, 'spec.changed')])], { refresh: async () => true })
    await settle()
    expect(ok.events).toHaveLength(1)
    const bad = harness([streamRes([], 401)])
    await settle()
    expect(bad.doFetch).toHaveBeenCalledTimes(1)
    expect(bad.statuses.at(-1)).toBe('stopped')
  })
  it('backs off on network errors and grows the delay', async () => {
    const h = harness([new Error('x'), new Error('y'), streamRes([frame(1, 'spec.changed')])])
    await settle()
    expect(h.waits.slice(0, 2)).toEqual([1000, 2000])
  })
  it('presence frames reach onPresence and do not move the cursor', async () => {
    const onPresence = vi.fn()
    const h = harness([streamRes([frame(null, 'presence', { users: [{ user_id: 'u', display: 'Maya', where: 'model' }] })]), streamRes([])], { onPresence })
    await settle()
    expect(onPresence).toHaveBeenCalledWith([{ user_id: 'u', display: 'Maya', where: 'model' }])
    expect(h.calls[1].headers['Last-Event-ID']).toBeUndefined()
  })
  it('close() stops without another fetch', async () => {
    const h = harness([streamRes([])])
    h.conn.close()
    await settle()
    expect(h.doFetch.mock.calls.length).toBeLessThanOrEqual(1)
  })
})
