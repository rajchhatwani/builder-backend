import { describe, expect, it } from 'vitest'
import { MAX_MS, parseRetryAfter, reconnectDelay } from './backoff'

describe('backoff schedule', () => {
  it('doubles up to the cap with jitter bounds', () => {
    const mid = () => 0.5
    expect([0, 1, 2, 3, 4, 5, 6, 20].map((a) => reconnectDelay(a, null, mid))).toEqual([1000, 2000, 4000, 8000, 16000, 30000, 30000, 30000])
    expect(reconnectDelay(2, null, () => 0)).toBe(3000)
    expect(reconnectDelay(2, null, () => 0.999)).toBeLessThanOrEqual(5000)
    expect(reconnectDelay(40, null, () => 0.999)).toBeLessThanOrEqual(MAX_MS * 1.25)
  })
  it('never undercuts Retry-After', () => {
    expect(reconnectDelay(0, 20, () => 0)).toBe(20000)
    expect(reconnectDelay(5, 2, () => 0.5)).toBe(30000)
    expect(reconnectDelay(0, 99999, () => 0.5)).toBe(120000)
  })
  it('parses Retry-After seconds only', () => {
    expect(parseRetryAfter('7')).toBe(7)
    expect(parseRetryAfter('Wed, 21 Oct')).toBeNull()
    expect(parseRetryAfter(null)).toBeNull()
  })
})
