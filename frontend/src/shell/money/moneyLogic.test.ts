import { describe, expect, it } from 'vitest'
import { buildInvoiceLines, defaultExponent, formatMinor, invoiceTotals, moneyErrorMessage, parseMajor, parseMoneyJson, parseStatementCsv, sumByCurrency, validSeller, type Invoice } from './moneyLogic'

const inv = (o: Partial<Invoice>): Invoice => ({ id: 'i', kind: 'receivable', number: '1', status: 'issued', counterparty: 'A', currency: 'USD', exponent: 2, issue_date: null, due_date: null, total_minor: 100, paid_minor: 0, outstanding_minor: 100, ...o })

describe('moneyLogic', () => {
  it('keeps digits beyond 2^53', () => {
    const j = parseMoneyJson('{"total_minor":9007199254740993,"x":5}') as { total_minor: string }
    expect(j.total_minor).toBe('9007199254740993')
    expect(formatMinor(j.total_minor, 2)).toBe('90,071,992,547,409.93')
  })
  it('formats and parses minor units', () => {
    expect(formatMinor(-1500, 3)).toBe('-1.500')
    expect(formatMinor(500, 0)).toBe('500')
    expect(parseMajor('12.34', 2)).toBe(1234n)
    expect(parseMajor('12.345', 2)).toBeNull()
    expect(parseMajor('-1', 2)).toBeNull()
    expect(parseMajor('-1.5', 2, true)).toBe(-150n)
  })
  it('sums per currency and totals invoices without floats', () => {
    expect([...sumByCurrency([{ c: 'A', a: '9007199254740993' }, { c: 'A', a: 1 }], (r) => r.c, (r) => r.a)]).toEqual([['A', 9007199254740994n]])
    const t = invoiceTotals([inv({}), inv({ total_minor: 50, outstanding_minor: 50 }), inv({ status: 'void', outstanding_minor: 100 }), inv({ currency: 'JPY', exponent: 0, total_minor: 7, outstanding_minor: 7 })])
    expect(t.map((x) => [x.currency, x.total, x.outstanding])).toEqual([['USD', 250n, 150n], ['JPY', 7n, 7n]])
  })
  it('builds invoice lines or explains the first problem', () => {
    const ok = buildInvoiceLines([{ description: ' Work ', quantity: '2', unitPrice: '10.50', taxRate: 'vat' }], 2)
    expect(ok.lines).toEqual([{ description: 'Work', quantity: 2, unit_price_minor: 1050, tax_rate: 'vat' }])
    expect(buildInvoiceLines([{ description: 'x', quantity: '1.5', unitPrice: '1', taxRate: '' }], 2).error).toMatch(/quantity/)
    expect(buildInvoiceLines([{ description: 'x', quantity: '1', unitPrice: '1.234', taxRate: '' }], 2).error).toMatch(/2 decimals/)
    expect(buildInvoiceLines([{ description: '', quantity: '1', unitPrice: '1', taxRate: '' }], 2).error).toMatch(/description/)
  })
  it('validates seller labels', () => {
    expect(validSeller('shop-1@x')).toBe(true)
    expect(validSeller('a b')).toBe(false)
    expect(validSeller('-a')).toBe(false)
  })
  it('parses statement CSV', () => {
    const r = parseStatementCsv('external_id,date,amount\nb1,2026-01-02,100.00,usd,INV-1\nb2,2026-01-03,-5.5', 2, 'USD')
    expect(r.lines).toEqual([{ external_id: 'b1', date: '2026-01-02', amount_minor: 10000, currency: 'USD', reference: 'INV-1' }, { external_id: 'b2', date: '2026-01-03', amount_minor: -550, currency: 'USD' }])
    expect(parseStatementCsv('b1,2026-01-02,1\nb1,2026-01-02,2', 2, 'USD').error).toMatch(/twice/)
    expect(parseStatementCsv('b1,2026-13-45,1', 2, 'USD').error).toMatch(/YYYY/)
    expect(parseStatementCsv('b1,2026-01-02,0', 2, 'USD').error).toMatch(/zero/)
    expect(parseStatementCsv('', 2, 'USD').error).toMatch(/at least/)
  })
  it('maps error codes to messages', () => {
    expect(moneyErrorMessage(409, { code: 'has_payments' })).toMatch(/cannot be voided/)
    expect(moneyErrorMessage(404, {}, 'payouts')).toMatch(/no payouts API/)
    expect(moneyErrorMessage(403, {})).toMatch(/role/)
    expect(moneyErrorMessage(500, { message: 'boom' })).toBe('boom')
  })
})

describe('defaultExponent matches the backend zero-decimal list', () => {
  it('treats every backend zero-decimal currency as exponent 0', () => {
    for (const c of ['CLP', 'ISK', 'JPY', 'KRW', 'PYG', 'RWF', 'UGX', 'VND', 'XAF', 'XOF', 'XPF']) expect(defaultExponent(c)).toBe(0)
    expect(defaultExponent('USD')).toBe(2)
  })
})
