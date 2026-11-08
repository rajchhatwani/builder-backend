import { afterEach, describe, expect, it, vi } from 'vitest'
import { aiApi } from './aiApi'

afterEach(() => vi.unstubAllGlobals())

describe('aiApi.decide binds the decision to what the reviewer saw (S3-004/5)', () => {
  it('POSTs expected_payload_hash and expected_spec_hash', async () => {
    const f = vi.fn(async () => new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('fetch', f)
    await aiApi.decide('p', 'a1', true, 'ok', undefined, { payload_hash: 'ph1', bound_spec_hash: 'sh1' })
    const calls = f.mock.calls as unknown as Array<[string, RequestInit]>
    expect(calls[0][0]).toContain('/agent/approvals/a1/decision')
    expect(JSON.parse(String(calls[0][1].body))).toEqual({ approve: true, note: 'ok', expected_payload_hash: 'ph1', expected_spec_hash: 'sh1' })
  })
  it('sends no hash when the approval has none (older rows)', async () => {
    const f = vi.fn(async () => new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('fetch', f)
    await aiApi.decide('p', 'a1', false, 'no', undefined, { payload_hash: null, bound_spec_hash: '' })
    const calls = f.mock.calls as unknown as Array<[string, RequestInit]>
    expect(JSON.parse(String(calls[0][1].body))).toEqual({ approve: false, note: 'no' })
  })
})
