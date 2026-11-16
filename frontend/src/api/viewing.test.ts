import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { openViewingTab, receiveViewingToken } from './viewing'

function msg(origin: string, source: unknown, data: unknown) {
  window.dispatchEvent(new MessageEvent('message', { origin, source: source as MessageEventSource, data }))
}

describe('viewing hand-off', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    Reflect.deleteProperty(window, 'opener')
  })

  it('opener ignores foreign origin and foreign source, then delivers on the real ready', async () => {
    const target = { postMessage: vi.fn() }
    vi.spyOn(window, 'open').mockReturnValue(target as unknown as Window)
    const p = openViewingTab('secret')
    msg('https://evil.example', target, { type: 'builder-viewing-ready' })
    msg(window.location.origin, {}, { type: 'builder-viewing-ready' })
    expect(target.postMessage).not.toHaveBeenCalled()
    msg(window.location.origin, target, { type: 'builder-viewing-ready' })
    expect(await p).toBe(true)
    expect(target.postMessage).toHaveBeenCalledWith({ type: 'builder-viewing-token', token: 'secret' }, window.location.origin)
  })

  it('opener resolves false on blocked pop-up and after 30s without ready', async () => {
    vi.spyOn(window, 'open').mockReturnValueOnce(null)
    expect(await openViewingTab('t')).toBe(false)
    vi.spyOn(window, 'open').mockReturnValueOnce({ postMessage: vi.fn() } as unknown as Window)
    const p = openViewingTab('t')
    vi.advanceTimersByTime(30_001)
    expect(await p).toBe(false)
  })

  it('viewing tab ignores foreign messages, accepts the opener, times out to null', async () => {
    const opener = { postMessage: vi.fn() }
    Object.defineProperty(window, 'opener', { value: opener, configurable: true })
    const p = receiveViewingToken()
    msg('https://evil.example', opener, { type: 'builder-viewing-token', token: 'bad' })
    msg(window.location.origin, {}, { type: 'builder-viewing-token', token: 'bad2' })
    msg(window.location.origin, opener, { type: 'builder-viewing-token', token: 'good' })
    expect(await p).toBe('good')

    const q = receiveViewingToken()
    vi.advanceTimersByTime(15_001)
    expect(await q).toBeNull()
  })

  it('viewing tab without an opener resolves null at once', async () => {
    Object.defineProperty(window, 'opener', { value: null, configurable: true })
    expect(await receiveViewingToken()).toBeNull()
  })
})
