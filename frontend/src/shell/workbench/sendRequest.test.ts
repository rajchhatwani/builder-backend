import { describe, expect, it, vi } from 'vitest'
import { sendRequest } from './sendRequest'

const okFetch = () => vi.fn(async () => new Response('{"ok":true}', { status: 201 })) as unknown as typeof fetch

describe('sendRequest', () => {
  it('sends no cookies, refuses redirects, sets bearer only as a header', async () => {
    const f = okFetch()
    const r = await sendRequest({ url: 'http://p.test/x', origin: 'http://p.test', method: 'POST', body: '{}', bearer: 'SECRET' }, f)
    expect(r.status).toBe(201)
    const [, init] = (f as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit]
    expect(init.credentials).toBe('omit')
    expect(init.redirect).toBe('error')
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer SECRET')
    expect(JSON.stringify(r)).not.toContain('SECRET')
  })
  it('refuses a URL outside the origin before calling fetch', async () => {
    const f = okFetch()
    await expect(sendRequest({ url: 'http://evil.test/x', origin: 'http://p.test', method: 'GET' }, f)).rejects.toThrow(/outside/)
    expect(f).not.toHaveBeenCalled()
  })
  it('turns a network failure into a readable error', async () => {
    const f = (async () => { throw new TypeError('x') }) as unknown as typeof fetch
    await expect(sendRequest({ url: 'http://p.test/x', origin: 'http://p.test', method: 'GET' }, f)).rejects.toThrow(/Could not reach/)
  })
  it('returns HTML as plain text (no parsing)', async () => {
    const f = (async () => new Response('<script>alert(1)</script>', { status: 500 })) as unknown as typeof fetch
    const r = await sendRequest({ url: 'http://p.test/x', origin: 'http://p.test', method: 'GET' }, f)
    expect(r.text).toBe('<script>alert(1)</script>')
  })
})
