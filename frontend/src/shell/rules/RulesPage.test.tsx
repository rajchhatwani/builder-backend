import { createElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { click, flush, mount, q, qa, typeInto } from '../ai/testUtils'
import { RulesPage } from './RulesPage'

const m = vi.hoisted(() => ({ entities: vi.fn(), machines: vi.fn(), check: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({
  ...(await orig<typeof import('../../api/client')>()),
  api: { listEntities: m.entities, getStateMachines: m.machines, checkExpression: m.check },
}))

const FIELDS = [{ name: 'amount', type: 'int', nullable: false }]
const OK = { ok: true, type: 'bool', fields: FIELDS, error: null }
const MACHINES = { state_machines: [{ entity: 'Invoice', field: 's', initial: 'a', transitions: [{ name: 'approve', to_state: 'b', when: 'amount > 1' }, { name: 'bad', to_state: 'c', when: 'zzz' }] }] }

beforeEach(() => {
  Object.values(m).forEach((f) => f.mockReset())
  window.location.hash = '#/p/p/rules'
  m.entities.mockResolvedValue({ items: [{ name: 'Invoice' }] })
  m.machines.mockResolvedValue(MACHINES)
  m.check.mockImplementation(async (_p: string, _e: string, expr: string) => (expr === 'zzz' ? { ok: false, type: null, fields: [], error: { message: 'unknown field zzz', pos: 0 } } : OK))
})

describe('RulesPage', () => {
  it('shows the empty state without entities', async () => {
    m.entities.mockResolvedValue({ items: [] })
    await mount(createElement(RulesPage, { projectId: 'p' }))
    expect(q('rules-empty')).not.toBeNull()
  })

  it('lists fields and checks guards, flagging the broken one', async () => {
    await mount(createElement(RulesPage, { projectId: 'p' }))
    expect(q('rules-fields')?.textContent).toContain('amount')
    expect(q('rules-guard-summary')?.textContent).toBe('1 of 2 guards are broken.')
    expect(document.querySelector('[data-guard="Invoice/bad"]')?.getAttribute('data-state')).toBe('broken')
  })

  it('checks a typed expression after the debounce and shows the type', async () => {
    vi.useFakeTimers()
    try {
      await mount(createElement(RulesPage, { projectId: 'p' }))
      await typeInto(document.querySelector('#rules-expression') as HTMLTextAreaElement, 'amount > 3')
      expect(q('rules-type')).toBeNull()
      await act(async () => { await vi.advanceTimersByTimeAsync(350) })
      await flush()
      expect(m.check).toHaveBeenCalledWith('p', 'Invoice', 'amount > 3', expect.anything())
      expect(q('rules-type')).not.toBeNull()
    } finally { vi.useRealTimers() }
  })

  it('focuses the guard named by ?rule= and notes an unknown one', async () => {
    window.location.hash = '#/p/p/rules?rule=Invoice.approve'
    await mount(createElement(RulesPage, { projectId: 'p' }))
    expect(document.querySelector('[data-linked="true"]')?.getAttribute('data-guard')).toBe('Invoice/approve')
    expect(q('rule-not-found')).toBeNull()
  })
  it('notes a ?rule= that matches no guard', async () => {
    window.location.hash = '#/p/p/rules?rule=nope'
    await mount(createElement(RulesPage, { projectId: 'p' }))
    expect(q('rule-not-found')?.textContent).toContain('nope')
    expect(qa('rules-guards').length).toBe(1)
  })

  it('shows a message and retry when the field list cannot load', async () => {
    let fail = true
    m.check.mockImplementation(async (_p: string, _e: string, expr: string) => {
      if (expr === 'true' && fail) throw new Error('boom')
      return OK
    })
    m.machines.mockResolvedValue({ state_machines: [] })
    await mount(createElement(RulesPage, { projectId: 'p' }))
    expect(q('rules-fields-error')?.textContent).toContain('Could not load fields')
    expect(document.body.textContent).not.toContain('Loading fields')
    fail = false
    await click(q('rules-fields-retry'))
    expect(q('rules-fields')?.textContent).toContain('amount')
    expect(q('rules-fields-error')).toBeNull()
  })
})
