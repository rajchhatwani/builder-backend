import { describe, expect, it } from 'vitest'
import type { ImportPreview, ImportRow } from '../../api/types'
import { applyRowSave, changedValues, deriveStep, entitiesOf, fixableFields, groupErrors, initialMapping, mappingBody, quotaMessage, startValue, summarise } from './importLogic'

export const ROW: ImportRow = {
  id: 'r3', row_no: 3, raw: { No: 'INV-3', Total: 'abc' }, record: null, status: 'rejected',
  errors: [
    { field: 'amount', code: 'invalid_decimal', message: 'must be a number' },
    { field: 'amount', code: 'invalid_decimal', message: 'must be a number' },
    { field: 'status', code: 'required', message: 'is required' },
  ],
}
const FIELDS = [{ name: 'invoice_no', required: true }, { name: 'amount', required: true }, { name: 'status', required: false }]

describe('importLogic', () => {
  it('reads entities and fields from the spec, skipping junk', () => {
    const spec = { entities: [{ name: 'Invoice', fields: [{ name: 'amount', required: true }, { name: 'x' }, 3] }, 'bad', { fields: [] }] }
    expect(entitiesOf(spec)).toEqual([{ name: 'Invoice', fields: [{ name: 'amount', required: true }, { name: 'x', required: false }] }])
    expect(entitiesOf({})).toEqual([])
  })

  it('builds the mapping body with nulls for unmapped fields', () => {
    expect(mappingBody(FIELDS, { invoice_no: 'No', amount: 'Total' }, 'amount', '')).toEqual({ invoice_no: 'No', amount: null, status: null })
    expect(mappingBody(FIELDS, { invoice_no: 'No' }, 'status', 'State')).toEqual({ invoice_no: 'No', amount: null, status: 'State' })
  })

  it('prefers the saved mapping over the suggestion', () => {
    const p = { mapping: {}, suggested_mapping: { amount: 'Total' } } as Pick<ImportPreview, 'mapping' | 'suggested_mapping'>
    expect(initialMapping(p)).toEqual({ amount: 'Total' })
    expect(initialMapping({ ...p, mapping: { amount: 'Sum' } })).toEqual({ amount: 'Sum' })
  })

  it('groups errors per field without duplicates', () => {
    expect(groupErrors(ROW.errors)).toEqual([{ field: 'amount', messages: ['must be a number'] }, { field: 'status', messages: ['is required'] }])
    expect(groupErrors([{ field: '', code: 'x', message: 'bad row' }])[0].field).toBe('(row)')
  })

  it('finds fixable fields and starting values', () => {
    expect(fixableFields(ROW, FIELDS)).toEqual(['amount', 'status'])
    expect(startValue(ROW, { amount: 'Total' }, 'amount')).toBe('abc')
    expect(startValue(ROW, {}, 'status')).toBe('')
  })

  it('sends only changed inputs', () => {
    expect(changedValues({ amount: 'abc', status: 'draft' }, ROW, { amount: 'Total' })).toEqual({ status: 'draft' })
  })

  it('derives the step', () => {
    const p = {} as ImportPreview
    expect(deriveStep({ preview: null, reviewing: false, done: false })).toBe('choose')
    expect(deriveStep({ preview: p, reviewing: false, done: false })).toBe('mapping')
    expect(deriveStep({ preview: p, reviewing: true, done: false })).toBe('review')
    expect(deriveStep({ preview: p, reviewing: true, done: true })).toBe('done')
  })

  it('summarises counts', () => {
    expect(summarise({ total: 3, accepted: 2, rejected: 1, duplicate: 0, fixed: 0 })).toBe('3 rows, 2 ready, 1 need fixing')
    expect(summarise({ total: 1, accepted: 0, rejected: 0, duplicate: 1, fixed: 1 })).toBe('1 row, 1 ready, 0 need fixing, 1 already imported')
  })

  it('moves a saved row from rejected to fixed only when valid', () => {
    const c = { total: 3, accepted: 2, rejected: 1, duplicate: 0, fixed: 0 }
    expect(applyRowSave(c, { ...ROW, status: 'rejected' })).toBe(c)
    expect(applyRowSave(c, { ...ROW, status: 'fixed' })).toEqual({ ...c, rejected: 0, fixed: 1 })
  })

  it('words the quota refusal with the limit', () => {
    const m = quotaMessage([{ metric: 'imports.rows', limit: 100, used: 100, period_end: '2026-12-01T00:00:00+00:00' }])
    expect(m).toContain('100 imported rows')
    expect(m).toContain('2026-12-01')
    expect(m).toContain('Nothing was imported')
    expect(quotaMessage([])).toContain('is used up')
  })
})
