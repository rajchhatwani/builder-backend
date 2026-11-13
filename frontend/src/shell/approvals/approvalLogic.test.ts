import { describe, expect, it } from 'vitest'
import { approvalErrorMessage, argsText, canAcknowledge, canDecide, canHandOff, canMarkOutcome, canReject, moveRow, pageInfo, riskLabel, successRate } from './approvalLogic'

describe('approvalLogic', () => {
  it('formats success rate from basis points', () => {
    expect(successRate(null)).toBe('no outcomes yet'); expect(successRate(undefined)).toBe('no outcomes yet')
    expect(successRate(10000)).toBe('100%'); expect(successRate(8750)).toBe('87.5%'); expect(successRate(3333)).toBe('33.33%')
    expect(successRate(99999)).toBe('100%'); expect(successRate(-5)).toBe('0%'); expect(successRate(Number.NaN)).toBe('no outcomes yet')
  })
  it('decides which buttons apply per status', () => {
    expect(canDecide('pending_approval')).toBe(true); expect(canDecide('suggested')).toBe(false)
    expect(canReject('suggested')).toBe(true); expect(canHandOff('pending_approval')).toBe(true); expect(canReject('executed')).toBe(false)
    expect(canAcknowledge('suggested')).toBe(true); expect(canAcknowledge('pending_approval')).toBe(false)
    expect(canMarkOutcome({ status: 'executed', outcome: null })).toBe(true)
    expect(canMarkOutcome({ status: 'failed' })).toBe(true); expect(canMarkOutcome({ status: 'acknowledged' })).toBe(true)
    expect(canMarkOutcome({ status: 'executed', outcome: 'success' })).toBe(false); expect(canMarkOutcome({ status: 'rejected' })).toBe(false)
  })
  it('labels risk and serialises args safely', () => {
    expect(riskLabel('high')).toBe('High risk'); expect(riskLabel('odd')).toBe('Risk odd')
    expect(argsText({ a: 1 })).toBe('{\n  "a": 1\n}'); expect(argsText(undefined)).toBe('{}')
    const c: Record<string, unknown> = {}; c.self = c; expect(argsText(c)).toBe('{}')
  })
  it('maps error codes to clear messages', () => {
    expect(approvalErrorMessage(409, { code: 'proposal_closed' })).toMatch(/already decided/)
    expect(approvalErrorMessage(409, { code: 'autonomy_refuses_execution' })).toMatch(/suggest-level/)
    expect(approvalErrorMessage(403, { code: 'self_approval_forbidden' })).toMatch(/someone else/)
    expect(approvalErrorMessage(403, { code: 'forbidden' })).toMatch(/may not do this/)
    expect(approvalErrorMessage(409, { code: 'outcome_already_set' })).toMatch(/already recorded/)
    expect(approvalErrorMessage(409, { code: 'outcome_not_allowed' })).toMatch(/only be recorded/)
    expect(approvalErrorMessage(422, { code: 'unknown_role' })).toMatch(/role/)
    expect(approvalErrorMessage(409, null)).toMatch(/can no longer change/)
    expect(approvalErrorMessage(404, null)).toMatch(/no longer exists/)
    expect(approvalErrorMessage(500, null)).toBe('The agents API answered 500.')
  })
  it('pages and roves', () => {
    expect(pageInfo(0, 20, 0)).toEqual({ from: 0, to: 0, hasPrev: false, hasNext: false })
    expect(pageInfo(45, 20, 20)).toEqual({ from: 21, to: 40, hasPrev: true, hasNext: true })
    expect(moveRow(3, 0, 'ArrowDown')).toBe(1); expect(moveRow(3, 2, 'End')).toBe(2); expect(moveRow(0, 0, 'Home')).toBe(0)
  })
})
