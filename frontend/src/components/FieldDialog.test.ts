import { describe, expect, it } from 'vitest'
import { parseDefault } from './FieldDialog'

describe('FieldDialog parseDefault precision', () => {
  it('keeps decimal digits exact as a string', () => {
    expect(parseDefault('12345678901234567.89', 'decimal')).toBe('12345678901234567.89')
    expect(parseDefault('0.15', 'decimal')).toBe('0.15')
  })
  it('keeps unsafe bigint exact, safe bigint a number', () => {
    expect(parseDefault('9007199254740993', 'bigint')).toBe('9007199254740993')
    expect(parseDefault('42', 'bigint')).toBe(42)
  })
  it('integer and float stay numbers; junk is rejected', () => {
    expect(parseDefault('7', 'integer')).toBe(7)
    expect(parseDefault('1.5', 'float')).toBe(1.5)
    expect(() => parseDefault('abc', 'decimal')).toThrow()
  })
})
