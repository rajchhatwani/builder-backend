import { createElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Organization } from '../api/types'
import { click, mount, q, qa, setInput } from '../shell/ai/testUtils'
import { OrgAiTab } from './OrgAiTab'
import { OrgUsageTab } from './OrgUsageTab'

const m = vi.hoisted(() => ({ settings: vi.fn(), update: vi.fn(), cost: vi.fn(), usage: vi.fn(), setLimit: vi.fn() }))
vi.mock('../api/client', async (orig) => ({
  ...(await orig<typeof import('../api/client')>()),
  api: { orgAiSettings: m.settings, updateOrgAiSettings: m.update, orgAiCost: m.cost, orgUsage: m.usage, setOrgUsageLimit: m.setLimit },
}))
const org = (role: 'owner' | 'admin' | 'member') => ({ id: 'o', name: 'Acme', slug: 'acme', kind: 'team', created_at: '', my_role: role, member_count: 3 }) as Organization
const SETTINGS = { has_api_key: true, api_key_hint: 'sk-…ab12', monthly_budget_micro_usd: 5_000_000 }
const COST = { month_start: '', month_cost_micro_usd: 1_500_000, total_cost_micro_usd: 9_000_000, monthly_budget_micro_usd: 5_000_000, items: [{ id: 'l1', project_id: null, model: 'm', task_class: 'plan', input_tokens: 10, output_tokens: 5, cost_micro_usd: 250_000, created_at: '2026-01-01T10:00:00Z' }], total: 1, limit: 20, offset: 0 }
const USAGE = { metrics: [{ metric: 'imports.rows', unit: 'rows', period: 'month', period_start: null, period_end: null, used: 95, limit: 100, refused: 2 }, { metric: 'search.reindex', unit: 'calls', period: 'day', period_start: null, period_end: null, used: 1, limit: null, refused: 0 }] }
beforeEach(() => { Object.values(m).forEach((f) => f.mockReset()); m.settings.mockResolvedValue(SETTINGS); m.cost.mockResolvedValue(COST); m.usage.mockResolvedValue(USAGE) })

describe('OrgAiTab', () => {
  it('shows key state and spend, and saves a new budget in micro-USD', async () => {
    m.update.mockResolvedValue({ ...SETTINGS, monthly_budget_micro_usd: 7_500_000 })
    await mount(createElement(OrgAiTab, { org: org('admin') }))
    expect(q('ai-key-state')?.textContent).toContain('sk-…ab12')
    expect(q('ai-cost-month')?.textContent).toContain('$1.50 of $5.00')
    expect(qa('ai-cost-row')).toHaveLength(1)
    await setInput(q('ai-budget') as HTMLInputElement, '7.5')
    await click(q('ai-save'))
    expect(m.update).toHaveBeenCalledWith('acme', { monthly_budget_micro_usd: 7_500_000 })
    expect(q('ai-saved')).not.toBeNull()
  })

  it('sends a typed key (never echoed) and can remove it', async () => {
    m.update.mockResolvedValue(SETTINGS)
    await mount(createElement(OrgAiTab, { org: org('owner') }))
    expect((q('ai-key') as HTMLInputElement).type).toBe('password')
    await setInput(q('ai-key') as HTMLInputElement, 'sk-' + 'a'.repeat(30))
    await click(q('ai-save'))
    expect(m.update).toHaveBeenCalledWith('acme', { api_key: 'sk-' + 'a'.repeat(30) })
    expect((q('ai-key') as HTMLInputElement).value).toBe('')
    await click(q('ai-clear-key'))
    expect(m.update).toHaveBeenLastCalledWith('acme', { clear_api_key: true })
  })

  it('shows nothing to members and does not call the API', async () => {
    await mount(createElement(OrgAiTab, { org: org('member') }))
    expect(q('ai-noaccess')).not.toBeNull()
    expect(m.settings).not.toHaveBeenCalled()
  })
})

describe('OrgUsageTab', () => {
  it('lists used, limit and refused; members cannot edit', async () => {
    await mount(createElement(OrgUsageTab, { org: org('member') }))
    const rows = qa('usage-row')
    expect(rows).toHaveLength(2)
    expect(rows[0].getAttribute('data-near-limit')).toBe('true')
    expect(rows[0].textContent).toContain('95')
    expect(rows[1].querySelector('[data-testid=usage-limit]')?.textContent).toBe('No limit')
    expect(q('usage-edit')).toBeNull()
  })

  it('lets the owner set a limit and clear it', async () => {
    m.setLimit.mockResolvedValue(USAGE)
    await mount(createElement(OrgUsageTab, { org: org('owner') }))
    await setInput(qa('usage-edit')[0] as HTMLInputElement, '250')
    await click(qa('usage-save')[0])
    expect(m.setLimit).toHaveBeenCalledWith('acme', 'imports.rows', 250)
    await click(qa('usage-clear')[0])
    expect(m.setLimit).toHaveBeenLastCalledWith('acme', 'imports.rows', null)
  })

  it('shows the refusal when the limit cannot be changed', async () => {
    m.setLimit.mockRejectedValueOnce(new Error('owner only'))
    await mount(createElement(OrgUsageTab, { org: org('owner') }))
    await setInput(qa('usage-edit')[0] as HTMLInputElement, '5')
    await click(qa('usage-save')[0])
    expect(q('usage-error')?.textContent).toBe('owner only')
  })
})
