import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, onQuotaExceeded } from './client'
import { setAccessToken } from './session'

function reply(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('api client', () => {
  const fetchMock = vi.fn()
  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
    setAccessToken('app', 'tok')
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    setAccessToken('app', null)
  })

  it('turns an error envelope into an ApiError with status, code and details', async () => {
    fetchMock.mockResolvedValueOnce(reply(409, { code: 'conflict', message: 'taken', details: [{ f: 1 }] }))
    const err = await api.getProject('p1').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 409, code: 'conflict', message: 'taken', details: [{ f: 1 }] })
  })

  it('sends the bearer token and credentials', async () => {
    fetchMock.mockResolvedValueOnce(reply(200, { id: 'p1' }))
    await api.getProject('p1')
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/projects/p1')
    expect(init.credentials).toBe('include')
    expect(init.headers.Authorization).toBe('Bearer tok')
  })

  it('resolves 204 responses to undefined without parsing a body', async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))
    await expect(api.deleteProject('p1')).resolves.toBeUndefined()
  })

  it('notifies listeners on 402 quota refusals and still throws', async () => {
    const seen = vi.fn()
    const off = onQuotaExceeded(seen)
    fetchMock.mockResolvedValueOnce(reply(402, { code: 'plan_limit', message: 'cap', details: [] }))
    await expect(api.getProject('p1')).rejects.toMatchObject({ status: 402 })
    expect(seen).toHaveBeenCalledOnce()
    off()
  })

  it('refreshes once on 401 and retries the original call', async () => {
    fetchMock
      .mockResolvedValueOnce(reply(401, { code: 'invalid_session', message: 'x', details: [] }))
      .mockResolvedValueOnce(reply(200, { access_token: 'new' })) // /account/refresh
      .mockResolvedValueOnce(reply(200, { id: 'p1' }))
    await expect(api.getProject('p1')).resolves.toEqual({ id: 'p1' })
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(String(fetchMock.mock.calls[1][0])).toContain('/account/refresh')
  })
})

describe('api client, unreadable bodies', () => {
  beforeEach(() => vi.stubGlobal('fetch', vi.fn()))
  afterEach(() => vi.unstubAllGlobals())
  it('turns a non-JSON error body into an ApiError with the status', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response('<html>Bad Gateway</html>', { status: 502 }))
    const err = await api.getProject('p1').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 502, code: 'bad_response' })
  })
  it('turns a non-JSON success body into an ApiError, not a SyntaxError', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response('not json', { status: 200 }))
    const err = await api.getProject('p1').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
  })
})
