import { describe, expect, it } from 'vitest'
import { aiErrorMessage, bpText, clip, effectiveStartMode, isDryMode, jsonText, pageInfo, usd } from './aiLogic'

describe('aiLogic', () => {
  it('formats micro-USD with integers only', () => {
    expect(usd(1_500_000)).toBe('1.500000')
    expect(usd(5)).toBe('0.000005')
    expect(usd(undefined)).toBe('0.000000')
    expect(usd(9007199254740993n)).toBe('9,007,199,254.740993')
  })
  it('formats basis points and survives junk', () => {
    expect(bpText(8750)).toBe('87.5%')
    expect(bpText(10000)).toBe('100%')
    expect(bpText(99999)).toBe('100%')
    expect(bpText(null)).toBe('n/a')
    expect(bpText(NaN)).toBe('n/a')
  })
  it('clips untrusted text and never throws on json', () => {
    expect(clip('a'.repeat(10), 4)).toBe('aaaa…')
    expect(clip(null)).toBe('')
    const c: Record<string, unknown> = {}; c.self = c
    expect(jsonText(c)).toBe('null')
    expect(jsonText({ a: 1 })).toContain('"a": 1')
  })
  it('pages', () => {
    expect(pageInfo(0, 50, 0)).toEqual({ from: 0, to: 0, hasPrev: false, hasNext: false })
    expect(pageInfo(120, 50, 50)).toEqual({ from: 51, to: 100, hasPrev: true, hasNext: true })
  })
  it('maps errors', () => {
    expect(aiErrorMessage(403, { code: 'forbidden' }, 'AI gateway')).toMatch(/role may not/)
    expect(aiErrorMessage(404, {}, 'AI gateway')).toMatch(/no AI gateway/)
    expect(aiErrorMessage(409, { code: 'eval_required' }, 'x')).toMatch(/eval/)
    expect(aiErrorMessage(500, { message: 'boom' }, 'x')).toBe('boom')
  })
  it('only suggest is dry; an unset mode runs at the agent autonomy', () => {
    expect(effectiveStartMode('', 'auto')).toBe('auto')
    expect(isDryMode(effectiveStartMode('', 'auto'))).toBe(false)
    expect(isDryMode(effectiveStartMode('suggest', 'auto'))).toBe(true)
    expect(isDryMode('draft')).toBe(false)
  })
})
