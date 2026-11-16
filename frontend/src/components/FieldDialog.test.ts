import { describe, expect, it } from 'vitest'
import { parseDefault } from './FieldDialog'

describe('FieldDialog parseDefault precision', () => {
  it('sends decimal defaults as numbers the API accepts', () => {
    expect(parseDefault('10.50', 'decimal')).toBe(10.5)
    expect(parseDefault('0.15', 'decimal')).toBe(0.15)
  })
  it('rejects decimals and bigints a JS number cannot hold exactly', () => {
    expect(() => parseDefault('12345678901234567.89', 'decimal')).toThrow()
    expect(() => parseDefault('9007199254740993', 'bigint')).toThrow()
    expect(parseDefault('42', 'bigint')).toBe(42)
  })
  it('integer and float stay numbers; junk is rejected', () => {
    expect(parseDefault('7', 'integer')).toBe(7)
    expect(parseDefault('1.5', 'float')).toBe(1.5)
    expect(() => parseDefault('abc', 'decimal')).toThrow()
  })
})
