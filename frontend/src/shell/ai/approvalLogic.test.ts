import { describe, expect, it } from 'vitest'
import { approvalIdFromHash, decisionGate, describePayload, effectiveState, expiryText, noteValid, reviewHref, tabOf } from './approvalLogic'

const NOW = Date.parse('2026-11-03T12:00:00Z')
const base = { state: 'pending', expires_at: '2026-11-04T12:00:00Z', requires_owner: false }

describe('approval logic', () => {
  it('treats a pending approval past its deadline as expired', () => {
    expect(effectiveState({ ...base, expires_at: '2026-11-03T11:00:00Z' }, NOW)).toBe('expired')
    expect(effectiveState(base, NOW)).toBe('pending')
    expect(effectiveState({ ...base, state: 'approved', expires_at: '2020-01-01T00:00:00Z' }, NOW)).toBe('approved')
    expect(tabOf({ state: 'superseded' })).toBe('decided')
  })
  it('words the remaining time', () => {
    expect(expiryText(base, NOW)).toBe('Expires in 24 h')
    expect(expiryText({ ...base, expires_at: '2026-11-03T12:30:00Z' }, NOW)).toBe('Expires in 30 min')
    expect(expiryText({ ...base, expires_at: '2026-11-10T12:00:00Z' }, NOW)).toBe('Expires in 7 days')
    expect(expiryText({ ...base, state: 'approved' }, NOW)).toBe('')
  })
  it('allows owner-only approvals only for owners, but never blocks when the role is unknown', () => {
    const o = { ...base, requires_owner: true }
    expect(decisionGate(o, 'editor', NOW).canDecide).toBe(false)
    expect(decisionGate(o, 'editor', NOW).reason).toMatch(/owner/)
    expect(decisionGate(o, 'owner', NOW).canDecide).toBe(true)
    expect(decisionGate(o, null, NOW).canDecide).toBe(true)
    expect(decisionGate(base, 'editor', NOW).canDecide).toBe(true)
    expect(decisionGate(base, 'viewer', NOW).canDecide).toBe(false)
  })
  it('blocks decided, expired and superseded requests', () => {
    expect(decisionGate({ ...base, expires_at: '2026-11-01T00:00:00Z' }, 'owner', NOW).reason).toMatch(/expired/)
    expect(decisionGate({ ...base, state: 'superseded' }, 'owner', NOW).canDecide).toBe(false)
    expect(decisionGate({ ...base, state: 'denied' }, 'owner', NOW).reason).toMatch(/denied/)
  })
  it('requires a note to deny only', () => {
    expect(noteValid(true, '')).toBe(true)
    expect(noteValid(false, '  ')).toBe(false)
    expect(noteValid(false, 'too broad')).toBe(true)
  })
  it('lists hooks, files, gate hash and unknown facts from a final C payload', () => {
    const d = describePayload({ summary: 'Done', final: true, gate_report_hash: 'abc', hooks: [{ name: 'on_save', author: 'ai' }, { name: 'old', author: 'human' }], files: ['hooks/on_save.py', 7], run_id: 'x', weird: { a: 1 } })
    expect(d.summary).toBe('Done')
    expect(d.hooks).toEqual([{ name: 'on_save', author: 'ai', ai: true }, { name: 'old', author: 'human', ai: false }])
    expect(d.files).toEqual(['hooks/on_save.py'])
    expect(d.gateHash).toBe('abc')
    expect(d.hasAiCode).toBe(true)
    expect(d.facts).toEqual([{ key: 'weird', value: '{"a":1}' }])
  })
  it('reads the single-hook review and D payloads', () => {
    expect(describePayload({ hook: 'h', file: 'f.py', sha256: 's', author: 'ai' })).toMatchObject({ hooks: [{ name: 'h', ai: true }], files: ['f.py'], hasAiCode: true })
    const d = describePayload({ op_type: 'remove_entity', name: 'Invoice', reason: 'unused' })
    expect(d.facts.map((f) => f.key)).toEqual(['op_type', 'name', 'reason'])
    expect(d.hasAiCode).toBe(false)
  })
  it('builds links', () => {
    expect(reviewHref('p', { id: 'a1', kind: 'A', run_id: 'r1' })).toBe('#/p/p/plan?run=r1')
    expect(reviewHref('p', { id: 'a1', kind: 'C', run_id: 'r1' })).toBe('#/p/p/approvals?approval=a1')
    expect(approvalIdFromHash('#/p/p/approvals?approval=12345678-aaaa')).toBe('12345678-aaaa')
    expect(approvalIdFromHash('#/p/p/approvals')).toBeNull()
  })
})
