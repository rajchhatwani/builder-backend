import { describe, expect, it } from 'vitest'
import {
  blankSequence, blankSetting, clientErrors, historyFromBody, historyToBody, issuesForSection, listFromBody, listToBody,
  looksSecret, parseIssuePath, previewNumber, sequenceFromBody, sequenceToBody, settingFromBody, settingToBody, textToRoles,
} from './formLogic'

describe('settings mapping', () => {
  it('round-trips an int setting (numbers stay numbers, roles become lists)', () => {
    const body = { key: 'approval_threshold', type: 'int', default: 1000, label: 'T', minimum: 0, maximum: 1000000, read_roles: ['manager', 'admin'], edit_roles: ['admin'] }
    const out = settingToBody(settingFromBody(body))
    expect(out).toMatchObject({ key: 'approval_threshold', type: 'int', default: 1000, minimum: 0, maximum: 1000000, read_roles: ['manager', 'admin'], edit_roles: ['admin'], max_length: null })
  })
  it('keeps decimals as strings and bools as booleans', () => {
    expect(settingToBody({ ...settingFromBody({ key: 'vat', type: 'decimal', default: '0.20', minimum: '0', maximum: '1' }) })).toMatchObject({ default: '0.20', minimum: '0', maximum: '1' })
    expect(settingToBody({ ...blankSetting(), key: 'b', type: 'bool', default: 'false' }).default).toBe(false)
    expect(settingFromBody({ key: 'b', type: 'bool', default: false }).default).toBe('false')
  })
  it('sends non-numeric text for an int as text so the backend can answer', () => {
    expect(settingToBody({ ...blankSetting(), key: 'x', type: 'int', default: 'abc' }).default).toBe('abc')
    expect(settingToBody({ ...blankSetting(), key: 'x', type: 'int', default: '' }).default).toBeNull()
  })
  it('an empty string default stays "" for string settings', () => {
    expect(settingToBody({ ...blankSetting(), key: 'x', type: 'string', default: '' }).default).toBe('')
  })
})

describe('sequences and lists mapping', () => {
  it('round-trips a sequence', () => {
    const b = { name: 'order_no', prefix: 'ORD-', padding: 4, start: 1, per_tenant: false, reset_yearly: true, view_roles: [] }
    expect(sequenceToBody(sequenceFromBody(b))).toEqual(b)
  })
  it('previews the next number like the generated helper', () => {
    expect(previewNumber({ ...blankSequence(), prefix: 'INV-', padding: '5', start: '42' })).toBe('INV-00042')
    expect(previewNumber({ ...blankSequence(), prefix: 'O-', padding: '3', reset_yearly: true }, 2026)).toBe('O-2026-001')
  })
  it('round-trips a list with items; blank colour becomes null', () => {
    const b = { name: 's', label: 'S', max_items: 12, edit_roles: ['admin'], items: [{ value: 'new', label: 'New', color: '#2563eb', locked: true }, { value: 'x', label: 'X', color: null, locked: false }] }
    expect(listToBody(listFromBody(b))).toEqual(b)
  })
})

describe('history mapping', () => {
  it('round-trips and splits roles on commas and spaces', () => {
    const b = { entity: 'Ticket', fields: ['subject', 'assignee'], retention_days: 365, view_roles: ['admin', 'auditor'] }
    expect(historyToBody(historyFromBody(b))).toEqual(b)
    expect(textToRoles(' admin,  manager ,,auditor ')).toEqual(['admin', 'manager', 'auditor'])
  })
  it('spots secret-looking names like the backend', () => {
    expect(looksSecret('API_KEY')).toBe(true)
    expect(looksSecret('subject')).toBe(false)
  })
})

describe('client checks', () => {
  it('only flags values that are not whole numbers', () => {
    expect(clientErrors('sequences', [{ ...blankSequence(), padding: 'x', start: '1' }])).toEqual({ '0.padding': 'Enter a whole number' })
    expect(clientErrors('sequences', [blankSequence()])).toEqual({})
    expect(clientErrors('history', [{ k: 1, entity: 'A', fields: [], retention_days: '-5', view_roles: '' }])).toEqual({})
    expect(clientErrors('history', [{ k: 1, entity: 'A', fields: [], retention_days: 'ten', view_roles: '' }])).toHaveProperty(['0.retention_days'])
  })
})

describe('issue path -> field', () => {
  it('parses paths', () => {
    expect(parseIssuePath('settings[0].default')).toEqual({ section: 'settings', index: 0, field: 'default' })
    expect(parseIssuePath('settings[2].read_roles[1]')).toEqual({ section: 'settings', index: 2, field: 'read_roles' })
    expect(parseIssuePath('lists[1].items[2].value')).toEqual({ section: 'lists', index: 1, field: 'items[2].value' })
    expect(parseIssuePath('history[0].fields[3]')).toEqual({ section: 'history', index: 0, field: 'fields[3]' })
    expect(parseIssuePath('settings')).toEqual({ section: 'settings', index: null, field: null })
    expect(parseIssuePath('lists[4]')).toEqual({ section: 'lists', index: 4, field: null })
  })
  it('keeps only this section and groups by row and field, messages untouched', () => {
    const issues = [
      { path: 'settings[0].default', code: 'out_of_range', message: 'default is above the maximum' },
      { path: 'settings[0].default', code: 'x', message: 'second' },
      { path: 'settings[1]', code: 'x', message: 'row level' },
      { path: 'settings', code: 'too_many', message: 'at most 200 settings' },
      { path: 'sequences[0].start', code: 'invalid_value', message: 'not mine' },
      { path: 'state_machines[0].initial', code: 'x', message: 'not mine either' },
    ]
    const r = issuesForSection('settings', issues)
    expect(r.section).toEqual(['at most 200 settings'])
    expect(r.rows[0].fields.default).toEqual(['default is above the maximum', 'second'])
    expect(r.rows[1].row).toEqual(['row level'])
    expect(Object.keys(r.rows)).toEqual(['0', '1'])
  })
})
