import { describe, expect, it } from 'vitest'
import { gateRows, budgetRows, canSeeItWork, friendlyStep, platformRow, stopInfo, pct, pollInterval, runActions, usd } from './buildLogic'

describe('build logic', () => {
  it('computes percentages safely', () => {
    expect(pct(5, 10)).toBe(50)
    expect(pct(20, 10)).toBe(100)
    expect(pct(1, null)).toBeNull()
    expect(pct(1, 0)).toBeNull()
  })
  it('flags budgets near and at the limit', () => {
    const rows = budgetRows({ budgets: { max_steps: 10, max_repairs: 3, max_cost_micro_usd: 2_000_000 }, steps_used: 8, repairs_used: 3, cost_micro_usd: 500_000 })
    expect(rows.map((r) => r.level)).toEqual(['warn', 'full', 'ok'])
    expect(rows[2].text).toBe('$0.5000 of $2.00')
  })
  it('tolerates missing limits', () => {
    const r = budgetRows({ budgets: {}, steps_used: 4, repairs_used: 0, cost_micro_usd: 0 })
    expect(r[0]).toMatchObject({ limit: null, pct: null, text: '4' })
    expect(usd(1_500_000)).toBe('$1.50')
  })
  it('polls every 3 s only while the run can change', () => {
    expect(pollInterval({ state: 'running' })).toBe(3000)
    expect(pollInterval({ state: 'awaiting_approval' })).toBe(3000)
    expect(pollInterval({ state: 'applied' })).toBeNull()
    expect(pollInterval({ state: 'cancelled' })).toBeNull()
    expect(pollInterval({ state: 'running' }, true)).toBeNull()
    expect(pollInterval(null)).toBeNull()
  })
  it('offers cancel while live and resume when it can continue', () => {
    expect(runActions({ state: 'running' }, 0)).toMatchObject({ cancel: true, resume: true })
    expect(runActions({ state: 'awaiting_approval' }, 1)).toMatchObject({ cancel: true, resume: false })
    expect(runActions({ state: 'stopped' }, 0)).toMatchObject({ cancel: false, resume: true })
    expect(runActions({ state: 'created' }, 0).resumeLabel).toBe('Start')
    expect(runActions({ state: 'applied' }, 0)).toMatchObject({ cancel: false, resume: false })
  })
})

describe('stop codes, system steps and platform budget', () => {
  it('explains apply_conflict and apply_failed', () => {
    expect(stopInfo(null)).toBeNull()
    expect(stopInfo('apply_conflict')?.text).toContain('Nothing was applied')
    expect(stopInfo('apply_conflict')?.next).toContain('owner')
    expect(stopInfo('apply_failed', 'disk full')?.next).toContain('disk full')
    expect(stopInfo('budget_steps', 'out of steps')?.text).toBe('out of steps')
  })
  it('turns system steps into friendly entries', () => {
    expect(friendlyStep({ kind: 'system', output: { apply_conflict: true } })?.tone).toBe('bad')
    expect(friendlyStep({ kind: 'system', output: { apply_failed: true } })?.text).toContain('could not be written')
    expect(friendlyStep({ kind: 'system', output: { draft: 'applied', ops: 3 } })?.tone).toBe('ok')
    expect(friendlyStep({ kind: 'system', output: { draft: 'discarded' } })?.text).toContain('thrown away')
    expect(friendlyStep({ kind: 'system', output: { note: 'x' } })).toBeNull()
    expect(friendlyStep({ kind: 'tool', output: { draft: 'applied' } })).toBeNull()
  })
  it('colours the platform budget and reports the limit', () => {
    const b = (spent: number, remaining: number | null, cap: number | null = 10_000_000) => platformRow({ cap_micro_usd: cap, spent_micro_usd: spent, reserved_micro_usd: 0, remaining_micro_usd: remaining })
    expect(b(1_000_000, 9_000_000).level).toBe('ok')
    expect(b(8_500_000, 1_500_000).level).toBe('warn')
    const full = b(10_000_000, 0)
    expect(full.level).toBe('full')
    expect(full.limitReached).toBe(true)
    expect(full.remaining).toBe('Limit reached')
    expect(b(500_000, null, null).pct).toBeNull()
  })
  it('offers See it work only for an applied run', () => {
    expect(canSeeItWork({ state: 'applied' })).toBe(true)
    expect(canSeeItWork({ state: 'stopped' })).toBe(false)
  })
})

describe('pause and gate-run logic', () => {
  it('pause only for a live, running, unpaused run', () => {
    expect(runActions({ state: 'running' }, 0).pause).toBe(true)
    expect(runActions({ state: 'running', paused_at: 'x' }, 0)).toMatchObject({ pause: false, paused: true, resume: true })
    expect(runActions({ state: 'applying' }, 0).pause).toBe(false)
    expect(runActions({ state: 'stopped' }, 0).pause).toBe(false)
    expect(runActions({ state: 'applied' }, 0).pause).toBe(false)
  })
  it('gates need a live run with a draft', () => {
    expect(runActions({ state: 'running', workspace_id: 'w' }, 0).gates).toBe(true)
    expect(runActions({ state: 'running', workspace_id: null }, 0).gates).toBe(false)
    expect(runActions({ state: 'applied', workspace_id: 'w' }, 0).gates).toBe(false)
  })
  it('gateRows reads any gate id and falls back across message keys', () => {
    expect(gateRows([{ rule_id: 'G-77', hint: 'h', actual: 'a', location: 'l' }])[0]).toMatchObject({ id: 'G-77', message: 'h' })
    expect(gateRows([{ gate: 'x', message: 'm' }])[0]).toMatchObject({ id: 'x', message: 'm' })
    expect(gateRows([{}])[0].id).toBe('check')
  })
})
