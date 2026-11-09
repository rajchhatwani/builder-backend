import { describe, expect, it } from 'vitest'
import { ApiError } from '../../api/client'
import {
  cronHint, cronLabel, definitionToForm, emptyMetricForm, emptyReportForm, entitiesOf, errorMessage, fieldsForAgg, formToDefinition,
  formToReport, formatGroups, formatValue, groupDigits, opsFor, presetOf, slotOf, slotText, toggleKey, validateMetricForm, validateReportForm,
} from './metricsLogic'

const SPEC = { entities: [{ name: 'Invoice', fields: [{ name: 'invoice_no', type: 'string' }, { name: 'amount', type: 'decimal' }, { name: 'paid', type: 'boolean' }, { name: 'bad' }, 3] }, 'x', { fields: [] }] }
const ENTITIES = entitiesOf(SPEC)
const INVOICE = ENTITIES[0]

describe('entities and field choices', () => {
  it('reads typed fields and skips junk', () => {
    expect(ENTITIES).toHaveLength(1)
    expect(INVOICE.fields.map((f) => f.name)).toEqual(['invoice_no', 'amount', 'paid', 'bad'])
  })
  it('offers numeric fields only for sum, avg, min, max', () => {
    for (const agg of ['sum', 'avg', 'min', 'max']) expect(fieldsForAgg(INVOICE, agg).map((f) => f.name)).toEqual(['amount'])
    expect(fieldsForAgg(INVOICE, 'count_distinct').map((f) => f.name)).toContain('invoice_no')
    expect(fieldsForAgg(undefined, 'sum')).toEqual([])
  })
  it('hides ordering operators for text fields', () => {
    expect(opsFor('string').map((o) => o.id)).not.toContain('gt')
    expect(opsFor('decimal').map((o) => o.id)).toContain('gte')
  })
})

describe('form <-> body', () => {
  it('builds a definition and keeps decimal filter text exact', () => {
    const form = { ...emptyMetricForm('Invoice'), key: ' open_total ', label: 'Open total', agg: 'sum', field: 'amount', group_by: 'paid', unit: 'USD', filters: [{ field: 'amount', op: 'gt', value: '10.10' }, { field: 'paid', op: 'eq', value: 'false' }] }
    const def = formToDefinition(form, INVOICE)
    expect(def).toEqual({
      key: 'open_total', label: 'Open total', entity: 'Invoice', agg: 'sum', field: 'amount', group_by: 'paid', unit: 'USD',
      filter: [{ field: 'amount', op: 'gt', value: '10.10' }, { field: 'paid', op: 'eq', value: false }],
    })
    expect(definitionToForm(def)).toEqual({ ...form, key: 'open_total' })
  })
  it('splits an "is one of" list and omits empty optionals', () => {
    const def = formToDefinition({ ...emptyMetricForm('Invoice'), key: 'k', label: 'K', filters: [{ field: 'invoice_no', op: 'in', value: 'A, B ,C' }] }, INVOICE)
    expect(def.filter[0].value).toEqual(['A', 'B', 'C'])
    expect('field' in def).toBe(false)
    expect('group_by' in def).toBe(false)
  })
})

describe('validation hints', () => {
  const ok = { ...emptyMetricForm('Invoice'), key: 'n', label: 'N' }
  it('accepts a plain count', () => expect(validateMetricForm(ok, ENTITIES, false, [])).toEqual([]))
  it('flags key, label, entity', () => {
    expect(validateMetricForm({ ...ok, key: 'Bad Key' }, ENTITIES, false, []).map((p) => p.field)).toEqual(['key'])
    expect(validateMetricForm({ ...ok, label: ' ' }, ENTITIES, false, []).map((p) => p.field)).toEqual(['label'])
    expect(validateMetricForm({ ...ok, entity: '' }, ENTITIES, false, []).map((p) => p.field)).toEqual(['entity'])
    expect(validateMetricForm(ok, ENTITIES, false, ['n'])[0].message).toMatch(/already exists/)
    expect(validateMetricForm(ok, ENTITIES, true, ['n'])).toEqual([])
  })
  it('needs a numeric field for sum', () => {
    expect(validateMetricForm({ ...ok, agg: 'sum' }, ENTITIES, false, [])[0].message).toMatch(/needs a field with numbers/)
    expect(validateMetricForm({ ...ok, agg: 'sum', field: 'invoice_no' }, ENTITIES, false, [])[0].message).toMatch(/cannot be used/)
    expect(validateMetricForm({ ...ok, agg: 'sum', field: 'amount' }, ENTITIES, false, [])).toEqual([])
  })
  it('checks filter rows', () => {
    const f = (value: string) => validateMetricForm({ ...ok, filters: [{ field: 'amount', op: 'gt', value }] }, ENTITIES, false, [])
    expect(f('')[0].message).toMatch(/enter a value/)
    expect(f('abc')[0].message).toMatch(/is a number/)
    expect(f('1.5')).toEqual([])
  })
})

describe('value formatting', () => {
  it('keeps exact decimal strings, never rounds through a float', () => {
    expect(formatValue('12345678901234567890.123456789')).toBe('12,345,678,901,234,567,890.123456789')
    expect(formatValue('0.1')).toBe('0.1')
    expect(formatValue('-1234.50')).toBe('-1,234.50')
    expect(formatValue(1234567)).toBe('1,234,567')
    expect(formatValue(0)).toBe('0')
  })
  it('handles empty values, units and odd text', () => {
    expect(formatValue(null)).toBe('No value yet')
    expect(formatValue('10', 'USD')).toBe('10 USD')
    expect(groupDigits('n/a')).toBe('n/a')
  })
  it('formats groups', () => {
    expect(formatGroups([{ key: 'a', value: 2 }, { key: null, value: '1.5' }])).toEqual([{ label: 'a', value: '2' }, { label: '(none)', value: '1.5' }])
    expect(formatGroups(null)).toEqual([])
  })
  it('reads report slots', () => {
    const values = { a: { value: '5' }, b: 7, c: { error: 'quota_exceeded' } }
    expect(slotText(slotOf(values, 'a'))).toBe('5')
    expect(slotText(slotOf(values, 'b'))).toBe('7')
    expect(slotText(slotOf(values, 'c'))).toMatch(/plan limit/)
    expect(slotText(slotOf(values, 'zz'))).toMatch(/No value was stored/)
  })
})

describe('schedules and reports', () => {
  it('labels presets and custom crons', () => {
    expect(cronLabel('0 8 * * 1-5')).toBe('Weekdays at 08:00')
    expect(presetOf('0 8 * * *')).toBe('daily')
    expect(presetOf('5 4 * * *')).toBe('custom')
    expect(cronLabel(' 5 4 * * * ')).toBe('Custom schedule (5 4 * * *)')
  })
  it('hints at a malformed cron', () => {
    expect(cronHint('0 8 * * *')).toBeNull()
    expect(cronHint('every day')).toMatch(/five parts/)
    expect(cronHint('0 8 * *')).toMatch(/five parts/)
  })
  it('validates and builds a report body', () => {
    const f = emptyReportForm()
    expect(validateReportForm(f).map((p) => p.field)).toEqual(['name', 'metrics'])
    const full = { ...f, name: ' Weekly ', metric_keys: toggleKey(toggleKey([], 'a'), 'b'), timezone: ' ' }
    expect(validateReportForm(full)).toEqual([])
    expect(formToReport(full)).toEqual({ name: 'Weekly', metric_keys: ['a', 'b'], schedule: '0 8 * * *', timezone: 'UTC', enabled: true })
    expect(toggleKey(['a', 'b'], 'a')).toEqual(['b'])
  })
})

describe('error messages', () => {
  const err = (code: string, details: unknown[] = []) => new ApiError(code === 'quota_exceeded' ? 429 : 409, { code, message: 'server text', details })
  it('spells out the stable codes', () => {
    expect(errorMessage(err('metric_in_use'), 'x')).toMatch(/still used by a report/)
    expect(errorMessage(err('metric_too_large'), 'x')).toMatch(/too many records/)
    expect(errorMessage(err('metric_invalid'), 'x')).toMatch(/not valid: server text/)
    expect(errorMessage(err('report_invalid'), 'x')).toMatch(/report is not valid/)
    expect(errorMessage(err('quota_exceeded', [{ limit: 5, used: 5, period_end: '2026-12-01T00:00:00Z' }]), 'x')).toMatch(/allows 5.*5 are used.*2026-12-01/)
    expect(errorMessage(err('quota_exceeded'), 'x')).toMatch(/limit is used up/)
    expect(errorMessage('boom', 'fallback')).toBe('fallback')
  })
})
