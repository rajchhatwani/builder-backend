import { expect, it } from 'vitest'
import { accessDraft } from './accessDraft'
import { sectionDraft } from './sectionDraft'
import { transitionDraft } from './transitionDraft'

it('keeps the original section version across later edits and resets after a discard', () => {
  const initial = sectionDraft(null, { type: 'set', rows: ['ticket'], version: 0 })
  const edited = sectionDraft(initial, { type: 'set', rows: ['comment'], version: 5 })
  expect(edited).toEqual({ rows: ['comment'], version: 0 })
  expect(sectionDraft(edited, { type: 'reset' })).toBeNull()
})

it('keeps the access revision and combines changes made in multiple layers', () => {
  const initial = accessDraft(null, { type: 'edit', version: 2, seq: 8, edits: { permissions: [] } })
  const edited = accessDraft(initial, { type: 'edit', version: 2, seq: 9, edits: { field_access: [] } })
  expect(edited).toEqual({ version: 2, seq: 8, edits: { permissions: [], field_access: [] } })
  expect(accessDraft(edited, { type: 'reset' })).toBeNull()
})


it('keeps transition goals, sources and the guard when switching its trigger', () => {
  const manual = { from: ['open'], to: 'closed', auto: false, roles: ['staff'], guard: 'urgent' }
  expect(transitionDraft(manual, { field: 'auto', value: true })).toEqual({ ...manual, auto: true })
})
