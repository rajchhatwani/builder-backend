import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { accessToken, onSessionLost, refreshOutcome, refreshSession, setAccessToken, setViewingOnly } from './session'

describe('session refresh', () => {
  const fetchMock = vi.fn()
  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
    setAccessToken('app', 'old')
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    setViewingOnly(false)
    setAccessToken('app', null)
  })

  it('shares one fetch between concurrent callers', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ access_token: 'new' }), { status: 200 }))
    const [a, b] = await Promise.all([refreshSession('app'), refreshSession('app')])
    expect(a && b).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(accessToken('app')).toBe('new')
  })

  it('a viewing-only tab never calls the server', async () => {
    setViewingOnly(true)
    expect(await refreshOutcome('app')).toBe('lost')
    expect(fetchMock).not.toHaveBeenCalled()
    expect(accessToken('app')).toBeNull()
  })

  it('401 from the refresh endpoint is lost and clears the token', async () => {
    fetchMock.mockResolvedValue(new Response('{}', { status: 401 }))
    expect(await refreshOutcome('app')).toBe('lost')
    expect(accessToken('app')).toBeNull()
  })

  it('5xx, 429 and network failures are unavailable and keep the token', async () => {
    fetchMock.mockResolvedValueOnce(new Response('{}', { status: 503 }))
    expect(await refreshOutcome('app')).toBe('unavailable')
    fetchMock.mockResolvedValueOnce(new Response('{}', { status: 429 }))
    expect(await refreshOutcome('app')).toBe('unavailable')
    fetchMock.mockRejectedValueOnce(new TypeError('offline'))
    expect(await refreshOutcome('app')).toBe('unavailable')
    expect(accessToken('app')).toBe('old')
  })

  it('onSessionLost listeners can unsubscribe', () => {
    const seen = vi.fn()
    const off = onSessionLost(seen)
    off()
    expect(seen).not.toHaveBeenCalled()
  })
})
