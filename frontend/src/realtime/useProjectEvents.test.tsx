import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { publishTopics, subscribeTopic } from './bus'
import { HEARTBEAT_MS, useProjectEvents } from './useProjectEvents'
import type { StreamOptions } from './projectStream'

const m = vi.hoisted(() => ({ connect: vi.fn(), beat: vi.fn(), list: vi.fn() }))
vi.mock('./projectStream', () => ({ connectProjectEvents: m.connect }))
vi.mock('../api/client', async (orig) => ({
  ...(await orig<typeof import('../api/client')>()),
  api: { presenceHeartbeat: m.beat, listPresence: m.list },
}))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

interface Conn { opts: StreamOptions; close: ReturnType<typeof vi.fn> }
let conns: Conn[] = []
let root: ReturnType<typeof createRoot>
let host: HTMLElement
let last: { status: string; users: unknown[] }

function Probe({ pid, section }: { pid: string; section: string }) {
  last = useProjectEvents(pid, section)
  return null
}
const qcStable = new QueryClient()
const tree = (pid: string, section = 'model') => createElement(QueryClientProvider, { client: qcStable }, createElement(Probe, { pid, section }))

beforeEach(() => {
  vi.useFakeTimers()
  conns = []
  m.connect.mockImplementation((opts: StreamOptions) => {
    const c = { opts, close: vi.fn() }
    conns.push(c)
    return c
  })
  m.beat.mockResolvedValue({}); m.list.mockResolvedValue([])
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
})
afterEach(() => {
  act(() => root.unmount()); host.remove(); vi.useRealTimers()
  Object.values(m).forEach((f) => f.mockReset())
})

describe('useProjectEvents', () => {
  it('ignores a closed stream reporting stopped after the project switched', async () => {
    await act(async () => { root.render(tree('a')) })
    await act(async () => { conns[0].opts.onStatus?.('live') })
    expect(last.status).toBe('live')
    await act(async () => { root.render(tree('b')) })
    expect(conns[0].close).toHaveBeenCalled()
    expect(last.status).toBe('connecting')
    await act(async () => { conns[0].opts.onStatus?.('stopped'); conns[0].opts.onPresence?.([{ user_id: 'x', display: 'x', where: 'y' }]) })
    expect(last.status).toBe('connecting')
    expect(last.users).toEqual([])
    await act(async () => { conns[1].opts.onStatus?.('live') })
    expect(last.status).toBe('live')
  })

  it('beats now and every interval, and stops while paused or stopped', async () => {
    await act(async () => { root.render(tree('a', 'rules')) })
    expect(m.beat).toHaveBeenCalledWith('a', 'rules')
    const n = m.beat.mock.calls.length
    await act(async () => { await vi.advanceTimersByTimeAsync(HEARTBEAT_MS) })
    expect(m.beat.mock.calls.length).toBe(n + 1)
    await act(async () => { conns[0].opts.onStatus?.('paused') })
    const paused = m.beat.mock.calls.length
    await act(async () => { await vi.advanceTimersByTimeAsync(HEARTBEAT_MS * 3) })
    expect(m.beat.mock.calls.length).toBe(paused)
    await act(async () => { conns[0].opts.onStatus?.('live') })
    expect(m.beat.mock.calls.length).toBe(paused + 1)
  })

  it('publishes topics to the bus for streamed events', async () => {
    await act(async () => { root.render(tree('a')) })
    const hit = vi.fn()
    const off = subscribeTopic('spec', hit)
    await act(async () => { conns[0].opts.onEvent({ id: 1, type: 'spec.changed', data: {} } as never) })
    off()
    expect(hit).toHaveBeenCalledTimes(1)
  })
})

describe('bus', () => {
  it('unsubscribes, and a throwing listener does not block the others', () => {
    const a = vi.fn(); const b = vi.fn()
    const offA = subscribeTopic('t', a); const offB = subscribeTopic('t', b)
    publishTopics(['t', 't'])
    expect([a.mock.calls.length, b.mock.calls.length]).toEqual([1, 1])
    offA()
    publishTopics(['t'])
    expect([a.mock.calls.length, b.mock.calls.length]).toEqual([1, 2])
    offB()
    publishTopics(['t'])
    expect(b.mock.calls.length).toBe(2)
  })
  it('keeps notifying the rest when a listener throws', () => {
    const bad = vi.fn(() => { throw new Error('x') }); const ok = vi.fn()
    const o1 = subscribeTopic('u', bad); const o2 = subscribeTopic('u', ok)
    const err = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    publishTopics(['u'])
    err.mockRestore()
    o1(); o2()
    expect(ok).toHaveBeenCalled()
  })
})
