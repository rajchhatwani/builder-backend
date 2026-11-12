import { describe, expect, it } from 'vitest'
import { booksBalance, buildEntries, formatMinor, ledgerErrorMessage, parseLedgerJson, parseMajor, sumByCurrency, type Account } from './ledgerLogic'

describe('formatMinor', () => {
  it.each([
    [1234, 2, '12.34'], [5, 2, '0.05'], [0, 2, '0.00'], [123456789, 2, '1,234,567.89'],
    [500, 0, '500'], [1234567, 0, '1,234,567'],
    [1500, 3, '1.500'], [7, 3, '0.007'],
    [-1234, 2, '-12.34'], [-5, 3, '-0.005'], [-500, 0, '-500'],
  ])('%s at exponent %s is %s', (minor, exp, out) => expect(formatMinor(minor, exp)).toBe(out))
  it('keeps every digit beyond 2^53 (strings and BigInt)', () => {
    expect(formatMinor('9007199254740993123', 2)).toBe('90,071,992,547,409,931.23')
    expect(formatMinor(-9007199254740993n, 0)).toBe('-9,007,199,254,740,993')
  })
  it('parses JSON big integers without rounding', () => {
    const j = parseLedgerJson('{"amount_minor": 9007199254740993, "n": 1}') as { amount_minor: string; n: number }
    expect(j.amount_minor).toBe('9007199254740993')
    expect(j.n).toBe(1)
  })
})

describe('parseMajor', () => {
  it('converts by exponent and refuses extra decimals or junk', () => {
    expect(parseMajor('12.34', 2)).toBe(1234n)
    expect(parseMajor('12', 2)).toBe(1200n)
    expect(parseMajor('500', 0)).toBe(500n)
    expect(parseMajor('1.5', 3)).toBe(1500n)
    expect(parseMajor('1.5', 0)).toBeNull()
    expect(parseMajor('1.234', 2)).toBeNull()
    expect(parseMajor('-1', 2)).toBeNull()
    expect(parseMajor('abc', 2)).toBeNull()
  })
})

describe('balance checks', () => {
  it('books balance only when every currency total is zero', () => {
    expect(booksBalance([{ sum_minor: 0 }, { sum_minor: '0' }])).toBe(true)
    expect(booksBalance([{ sum_minor: 0 }, { sum_minor: -1 }])).toBe(false)
    expect(booksBalance([])).toBe(true)
  })
  it('sums entries per currency', () => {
    const m = sumByCurrency([{ currency: 'USD', amount_minor: 100 }, { currency: 'USD', amount_minor: -100 }, { currency: 'JPY', amount_minor: 5 }])
    expect(m.get('USD')).toBe(0n)
    expect(m.get('JPY')).toBe(5n)
  })
})

describe('buildEntries', () => {
  const accts: Account[] = [{ id: 'a', code: '1', name: 'Cash', kind: 'asset', currency: 'USD', exponent: 2 }, { id: 'b', code: '2', name: 'Rev', kind: 'income', currency: 'JPY', exponent: 0 }]
  it('signs debit positive and credit negative in minor units', () => {
    const r = buildEntries([{ accountId: 'a', side: 'debit', amount: '10.50' }, { accountId: 'b', side: 'credit', amount: '7' }], accts)
    expect(r.entries).toEqual([{ account_id: 'a', amount_minor: 1050 }, { account_id: 'b', amount_minor: -7 }])
  })
  it('reports the first problem', () => {
    expect(buildEntries([{ accountId: 'a', side: 'debit', amount: '1' }], accts).error).toMatch(/at least two/)
    expect(buildEntries([{ accountId: 'a', side: 'debit', amount: '1' }, { accountId: '', side: 'credit', amount: '1' }], accts).error).toMatch(/Entry 2: choose an account/)
    expect(buildEntries([{ accountId: 'a', side: 'debit', amount: '1' }, { accountId: 'b', side: 'credit', amount: '1.5' }], accts).error).toMatch(/at most 0 decimals for JPY/)
    expect(buildEntries([{ accountId: 'a', side: 'debit', amount: '0' }, { accountId: 'b', side: 'credit', amount: '1' }], accts).error).toMatch(/zero/)
  })
})

describe('ledgerErrorMessage', () => {
  it('formats unbalanced details per currency with the right exponent', () => {
    const m = ledgerErrorMessage(422, { code: 'unbalanced', message: 'x', details: [{ currency: 'KWD', sum_minor: -1500 }] }, { KWD: 3 })
    expect(m).toMatch(/does not balance/)
    expect(m).toContain('KWD is off by -1.500')
  })
  it('maps reverse conflicts and auth failures', () => {
    expect(ledgerErrorMessage(409, { code: 'already_reversed', message: '', details: [] })).toBe('This transaction has already been reversed.')
    expect(ledgerErrorMessage(401, {})).toMatch(/token was not accepted/)
    expect(ledgerErrorMessage(500, null)).toMatch(/answered 500/)
  })
})
