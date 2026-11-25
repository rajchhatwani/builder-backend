import { expect, it } from 'vitest'
import { emptyMetricForm, emptyReportForm } from '../../../../shell/metrics/metricsLogic'
import { initialSchemaDraft, schemaDraftReducer } from '../../../patterns/schemaDraft'
import { validCron } from '../../../validators/operate'
import { createDraft, metricDraft, reportDraft } from './metrics'
import { initialTrace, traceReducer } from './trace'

it('versioned forms keep their first edit version across subsequent edits and reset on reload', () => {
  const first = schemaDraftReducer(initialSchemaDraft, { type: 'edit', path: ['enabled'], next: true, version: 3, base: { enabled: false } })
  const second = schemaDraftReducer(first, { type: 'edit', path: ['queue'], next: 'postgres', version: 4, base: { enabled: false } })
  expect(second.draft).toEqual({ version: 3, value: { enabled: true, queue: 'postgres' } })
  expect(schemaDraftReducer(second, { type: 'reset' }).draft).toBeUndefined()
})

it('metric filter editing and removal preserve the other filters', () => {
  const filter = { field: 'amount', op: 'gte', value: '1' }
  const start = metricDraft(createDraft(emptyMetricForm()), { type: 'filter-add', filter })
  const added = metricDraft(start, { type: 'filter-add', filter: { ...filter, value: '2' } })
  const changed = metricDraft(added, { type: 'filter-update', index: 0, value: { op: 'eq' } })
  const removed = metricDraft(changed, { type: 'filter-remove', index: 1 })
  expect(removed.value.filters).toEqual([{ ...filter, op: 'eq' }])
})

it('report drafts retain the custom schedule choice while another field changes', () => {
  const custom = reportDraft(createDraft(emptyReportForm()), { type: 'update', custom: true, value: { schedule: '1 0 * * *' } })
  const changed = reportDraft(custom, { type: 'update', value: { timezone: 'Asia/Kolkata' } })
  expect(changed.custom).toBe(true)
  expect(changed.value.schedule).toBe('1 0 * * *')
})

it('trace errors retain the draft for correction and clear ends the read', () => {
  const reading = traceReducer({ ...initialTrace, draft: '{' }, { type: 'file' })
  const failed = traceReducer(reading, { type: 'failed', error: 'broken JSON' })
  expect(failed).toEqual({ draft: '{', error: 'broken JSON', reading: false })
  expect(traceReducer(reading, { type: 'clear' })).toEqual(initialTrace)
})

it('validates the cron grammar and rejects unimplemented syntax and out-of-range numbers', () => {
  expect(validCron('*/15 8-17/2 * * 1,3,5')).toBe(true)
  for (const value of ['0 8 * * MON', '0 8 * * 7', '70 8 * * 1', '5/2 8 * * 1', '0 9-8 * * 1', '0 8 0 * *']) {
    expect(validCron(value), value).toBe(false)
  }
})
