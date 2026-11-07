import { describe, expect, it } from 'vitest'
import { addRow, editedInfo, gateAFor, isEdited, isEmptyPlan, planBody, keptPlan, planRows, toggleRow } from './planLogic'
import { runIdFromHash } from './useRunParam'

const payload = { plan: { entities: ['Invoice'], hooks: [], zones: ['billing'], dependencies: ['pdfkit'], junk: ['x'] } }

describe('plan table', () => {
  it('reads rows from the Gate A payload', () => {
    expect(planRows(payload).map((r) => `${r.key}:${r.value}`)).toEqual(['entities:Invoice', 'zones:billing', 'dependencies:pdfkit'])
    expect(planRows({})).toEqual([])
    expect(planRows({ plan: 'oops' })).toEqual([])
  })
  it('tracks edits and builds a change request', () => {
    const orig = planRows(payload)
    expect(isEdited(orig, orig)).toBe(false)
    const rows = addRow(toggleRow(orig, 2), 'entities', ' Customer ')
    expect(isEdited(rows, orig)).toBe(true)
    expect(keptPlan(rows)).toEqual({ entities: ['Invoice', 'Customer'], hooks: [], zones: ['billing'], dependencies: [] })
    expect(planBody(rows).dependencies).toEqual([])
    expect(isEmptyPlan(rows)).toBe(false)
    expect(isEmptyPlan(orig.map((r) => ({ ...r, removed: true })))).toBe(true)
    expect(addRow(rows, 'entities', 'Customer')).toBe(rows)
    expect(addRow(rows, 'zones', '  ')).toBe(rows)
  })
  it('reads edited_from and picks the gate to show', () => {
    expect(editedInfo({})).toBeNull()
    const e = editedInfo({ edited_from: { entities: ['A', 'B'] }, edited_by: 'ann' })
    expect(e?.from.map((r) => r.value)).toEqual(['A', 'B'])
    expect(e?.by).toBe('ann')
    const ap = (id: string, state: string, at: string) => ({ id, kind: 'A', state, created_at: at }) as never
    expect(gateAFor([ap('1', 'approved', '2026-01-01'), ap('2', 'denied', '2026-02-01')])?.id).toBe('2')
    expect(gateAFor([ap('1', 'approved', '2026-03-01'), ap('2', 'pending', '2026-02-01')])?.id).toBe('2')
    expect(gateAFor([])).toBeNull()
  })
  it('reads the run id from the hash', () => {
    expect(runIdFromHash('#/p/abc/build?run=0f0f0f0f-1111-2222-3333-444444444444')).toBe('0f0f0f0f-1111-2222-3333-444444444444')
    expect(runIdFromHash('#/p/abc/build')).toBeNull()
  })
})
