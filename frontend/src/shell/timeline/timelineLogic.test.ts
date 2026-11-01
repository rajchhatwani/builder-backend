import { describe, expect, it } from 'vitest'
import type { SpecOp } from '../../api/types'
import { actorLabel, canRestore, failureMessage, formatWhen, impactText, latestSeq, opSummary, opsToUndo } from './timelineLogic'

const op = (seq: number, op_type: string, payload: Record<string, unknown> = {}, extra: Partial<SpecOp> = {}): SpecOp => ({
  id: `id-${seq}`, project_id: 'p', seq, op_type, origin: 'do', ref_seq: null,
  actor: { kind: 'user', user_id: 'u1', email: 'a@b.co' }, payload, inverse: { op_type: 'x', payload: {} },
  spec_hash_before: 'h0', spec_hash_after: 'h1', created_at: '2026-11-02T10:00:00Z', ...extra,
})
// newest first, like the API
const LOG = [op(3, 'update_field', { entity: 'Invoice', name: 'total' }), op(2, 'add_field', { entity: 'Invoice', field: { name: 'total' } }), op(1, 'add_entity', { entity: { name: 'Invoice' } })]

describe('opSummary', () => {
  it('names the operation and what it touched', () => {
    expect(opSummary(LOG[0])).toBe('Changed field Invoice.total')
    expect(opSummary(LOG[1])).toBe('Added field Invoice.total')
    expect(opSummary(LOG[2])).toBe('Added entity Invoice')
    expect(opSummary(op(4, 'set_section', { section: 'state_machines' }))).toBe('Replaced section state machines')
  })
  it('handles restore, undo, redo and unknown operations without throwing', () => {
    expect(opSummary(op(5, 'replace_spec', {}, { origin: 'restore', ref_seq: 2 }))).toBe('Restored the spec to version 2')
    expect(opSummary(op(6, 'remove_entity', { name: 'X' }, { origin: 'undo' }))).toBe('Undid: Removed entity X')
    expect(opSummary(op(7, 'remove_entity', { name: 'X' }, { origin: 'redo' }))).toBe('Redid: Removed entity X')
    expect(opSummary(op(8, 'brand_new_op', { weird: 1 }))).toBe('Brand new op')
    expect(opSummary(op(9, 'add_field', { entity: 5, field: null }))).toBe('Added field')
  })
})

describe('actorLabel / formatWhen', () => {
  it('prefers the email, then falls back', () => {
    expect(actorLabel(LOG[0])).toBe('a@b.co')
    expect(actorLabel({ actor: { kind: 'user', user_id: 'u', email: null } })).toBe('A user (since removed)')
    expect(actorLabel({ actor: { kind: 'builder_agent', user_id: null } })).toBe('Builder agent')
  })
  it('is relative when recent and tolerates a bad date', () => {
    const now = new Date('2026-11-02T10:00:30Z')
    expect(formatWhen('2026-11-02T10:00:00Z', now)).toBe('just now')
    expect(formatWhen('2026-11-02T09:50:00Z', now)).toBe('10 min ago')
    expect(formatWhen('not a date')).toBe('not a date')
  })
})

describe('restore preview', () => {
  it('lists the operations a restore would take back', () => {
    expect(opsToUndo(LOG, 1).map((o) => o.seq)).toEqual([3, 2])
    expect(opsToUndo(LOG, 3)).toEqual([])
    expect(opsToUndo(LOG, 0)).toHaveLength(3)
    expect(latestSeq(LOG)).toBe(3)
    expect(latestSeq([])).toBe(0)
  })
  it('only offers restore for an older version', () => {
    expect(canRestore(LOG, 1)).toBe(true)
    expect(canRestore(LOG, 0)).toBe(true)
    expect(canRestore(LOG, 3)).toBe(false)
    expect(canRestore([], 0)).toBe(false)
  })
  it('counts by kind', () => {
    expect(impactText(opsToUndo(LOG, 0))).toBe('3 changes: 1 changed field, 1 added field, 1 added entity')
    expect(impactText([LOG[0]])).toBe('1 change: 1 changed field')
    expect(impactText([])).toMatch(/already at this version/)
  })
})

describe('failureMessage', () => {
  it('treats spec_conflict as a reload case', () => {
    const f = failureMessage({ status: 409, code: 'spec_conflict', message: 'x' })
    expect(f.conflict).toBe(true)
    expect(f.text).toMatch(/Someone else changed/)
  })
  it('maps the other codes and falls back to the server message', () => {
    expect(failureMessage({ status: 409, code: 'nothing_to_undo' })).toEqual({ conflict: false, text: 'There is nothing to undo.' })
    expect(failureMessage({ status: 403, code: 'forbidden' }).text).toMatch(/permission/)
    expect(failureMessage({ status: 404, code: 'not_found' }).conflict).toBe(true)
    expect(failureMessage({ status: 422, code: 'spec_invalid', message: 'bad' }).text).toBe('bad')
    expect(failureMessage(null).text).toMatch(/Nothing was changed/)
  })
})
