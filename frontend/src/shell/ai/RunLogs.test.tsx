import { act, createElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MAX_RECONNECTS } from './stageLogic'
import { RunLogs } from './RunLogs'
import { click, flush, mount, q, qa, unmount } from './testUtils'

const enc = new TextEncoder()
const stream = (chunks: string[], status = 200, hold = false) => new Response(new ReadableStream({
  start(c) { chunks.forEach((x) => c.enqueue(enc.encode(x))); if (!hold) c.close() },
}), { status })
const status = () => q('log-status')?.getAttribute('data-status')

beforeEach(() => { vi.useFakeTimers() })
afterEach(() => { vi.useRealTimers() })

describe('RunLogs', () => {
  it('sends the token header with no credentials and renders each event kind', async () => {
    const f = vi.fn(async () => stream(['event: info\ndata: hello\n\n', 'data: line one\n\n', 'event: state\ndata: waking\n\n'], 200, true)) as unknown as typeof fetch
    await mount(createElement(RunLogs, { previewId: 'pv', token: 'tok', doFetch: f }))
    const init = (f as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1] as RequestInit
    expect(init.headers).toMatchObject({ 'X-Preview-Token': 'tok', Accept: 'text/event-stream' })
    expect(init.credentials).toBe('omit')
    expect(qa('log-line').map((l) => l.textContent)).toEqual(['hello', 'line one', 'preview state: waking'])
    expect(status()).toBe('sleeping')
  })
  it('pause freezes the view, resume shows buffered lines, clear empties', async () => {
    const f = vi.fn(async () => stream(['data: a\n\n'], 200, true)) as unknown as typeof fetch
    await mount(createElement(RunLogs, { previewId: 'pv', token: 'tok', doFetch: f }))
    expect(qa('log-line')).toHaveLength(1)
    await click(q('log-pause'))
    expect(q('log-pause')?.getAttribute('aria-pressed')).toBe('true')
    await click(q('log-clear'))
    expect(qa('log-line')).toHaveLength(0)
    expect(q('log-box')?.textContent).toMatch(/No log lines yet/)
  })
  it.each([[410, 'gone'], [401, 'token'], [403, 'token']])('stops at %i without reconnecting', async (code, st) => {
    const f = vi.fn(async () => stream([], code)) as unknown as typeof fetch
    await mount(createElement(RunLogs, { previewId: 'pv', token: 'tok', doFetch: f }))
    await act(async () => { await vi.advanceTimersByTimeAsync(120_000) })
    expect(status()).toBe(st)
    expect(f).toHaveBeenCalledTimes(1)
  })
  it('stops for good when the server says the preview was switched off', async () => {
    const f = vi.fn(async () => stream(['event: end\ndata: preview switched off\n\n'])) as unknown as typeof fetch
    await mount(createElement(RunLogs, { previewId: 'pv', token: 'tok', doFetch: f }))
    await act(async () => { await vi.advanceTimersByTimeAsync(120_000) })
    expect(status()).toBe('ended')
    expect(f).toHaveBeenCalledTimes(1)
  })
  it('a server that emits one line and closes cannot reconnect forever (S3-008)', async () => {
    const f = vi.fn(async () => stream(['data: x\n\n'])) as unknown as typeof fetch
    await mount(createElement(RunLogs, { previewId: 'pv', token: 'tok', doFetch: f }))
    await act(async () => { await vi.advanceTimersByTimeAsync(10 * 60_000) })
    expect(status()).toBe('error')
    expect(f).toHaveBeenCalledTimes(MAX_RECONNECTS + 1)
  })
  it('aborts the stream and stops retrying on unmount', async () => {
    let signal: AbortSignal | undefined
    const f = vi.fn(async (_u: string, init: RequestInit) => { signal = init.signal as AbortSignal; return stream([], 500) }) as unknown as typeof fetch
    await mount(createElement(RunLogs, { previewId: 'pv', token: 'tok', doFetch: f }))
    expect(status()).toBe('reconnecting')
    unmount()
    expect(signal?.aborted).toBe(true)
    await act(async () => { await vi.advanceTimersByTimeAsync(120_000) })
    expect(f).toHaveBeenCalledTimes(1)
  })
  it('shows the idle prompt when there is no token', async () => {
    const f = vi.fn() as unknown as typeof fetch
    await mount(createElement(RunLogs, { previewId: 'pv', token: '', doFetch: f }))
    await flush()
    expect(status()).toBe('idle')
    expect(q('log-box')?.textContent).toMatch(/Add a preview token/)
    expect(f).not.toHaveBeenCalled()
  })
})
