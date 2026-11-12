import { createElement } from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { ApiError } from '../../api/client'
import { click, flush, mount, q, qa } from '../ai/testUtils'
import { MigrationPlanSection } from './MigrationPlanView'

const m = vi.hoisted(() => ({ plan: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({ ...(await orig<typeof import('../../api/client')>()), api: { migrationPlan: m.plan } }))

const RESP = {
  plan: {
    steps: [{ seq: 1, phase: 1, kind: 'add_column', entity: 'Invoice', table: 'invoice', field: 'due', safety: 'safe', reason: 'new field', suggested_action: null, backfill_strategy: 'default', sql_hint: 'ALTER TABLE', note: null }],
    ignored_sections: ['hooks'], requires_confirmation: false, requires_backfill: true, highest_safety: 'safe',
  },
  text: 'Step 1', old_spec_hash: 'a', new_spec_hash: 'b', against_generation_id: null, first_generation: false, old_snapshot_unusable: false, allow_destructive_required: false,
}
beforeEach(() => m.plan.mockReset())

describe('MigrationPlanSection', () => {
  it('requests the plan and renders steps, backfill and ignored sections', async () => {
    m.plan.mockResolvedValue(RESP)
    await mount(createElement(MigrationPlanSection, { projectId: 'p' }))
    expect(q('migplan-result')).toBeNull()
    await click(q('migplan-run'))
    expect(m.plan).toHaveBeenCalledWith('p', {}, false)
    expect(qa('migplan-step')).toHaveLength(1)
    expect(q('migplan-summary')?.textContent).toContain('1 step')
    expect(q('migplan-summary')?.textContent).toContain('needs a backfill')
    expect(q('migplan-ignored')?.textContent).toContain('hooks')
    expect(q('migplan-text')?.textContent).toBe('Step 1')
  })

  it('offers the empty-baseline retry when the old snapshot is unreadable', async () => {
    m.plan.mockResolvedValueOnce({ ...RESP, old_snapshot_unusable: true })
    await mount(createElement(MigrationPlanSection, { projectId: 'p' }))
    await click(q('migplan-run'))
    m.plan.mockResolvedValueOnce(RESP)
    await click(q('migplan-accept-unreadable'))
    expect(m.plan).toHaveBeenLastCalledWith('p', {}, true)
  })

  it('shows the server message when planning fails', async () => {
    m.plan.mockRejectedValueOnce(new ApiError(403, { code: 'forbidden', message: 'editor only', details: [] }))
    await mount(createElement(MigrationPlanSection, { projectId: 'p' }))
    await click(q('migplan-run'))
    await flush()
    expect(q('migplan-error')?.textContent).toBe('editor only')
  })
})
