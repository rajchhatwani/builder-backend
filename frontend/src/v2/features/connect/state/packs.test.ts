import { expect, it } from 'vitest'
import { changePack, readPack } from '../api/packs'
import { bookingKindDefaults, changeBookingMode } from './packs'
import { initialSchemaDraft, schemaDraftReducer, shownErrors } from './schemaDraft'
import { packDraftIssues, reconciliationCeiling } from '../../../validators'

it('removes the last declared nested block even when siblings are serialized as null', () => {
  const original = { operations: { geo: { provider: 'fake' }, location: null, matching: null }, ai: { gateway: {} } }
  expect(readPack(original, ['operations', 'geo'])).toEqual({ provider: 'fake' })
  expect(changePack(original, ['operations', 'geo'], null)).toEqual({ ai: original.ai })
  expect(original.operations.geo).toEqual({ provider: 'fake' })
})

it('preserves the first edited version and clears related errors when the mode changes', () => {
  const base = { kinds: [{ ...bookingKindDefaults, name: 'desk', schedule: { mon: [{ start: '09:00', end: '10:00' }] } }] }
  const first = schemaDraftReducer(initialSchemaDraft, { type: 'edit', base, version: 3, path: ['kinds', 0, 'name'], next: 'office' })
  const failed = schemaDraftReducer(first, { type: 'errors', errors: { 'kinds.0.schedule': ['Opening window is required.'] } })
  const kind = (first.draft!.value as typeof base).kinds[0]
  const next = schemaDraftReducer(failed, { type: 'edit', base, version: 4, path: ['kinds', 0], next: changeBookingMode(kind, 'pool') })
  expect(next.draft).toMatchObject({ version: 3, value: { kinds: [{ name: 'office', mode: 'pool', capacity: 1, schedule: {} }] } })
  expect(shownErrors(next, {})).toEqual({})
})

it('uses payment exponents for the tolerance and detects overlap in booking windows', () => {
  expect(reconciliationCeiling(['USD', 'JPY'])).toBe(100)
  expect(reconciliationCeiling(['ISK', 'BHD'])).toBe(10_000)
  const issues = packDraftIssues('booking', { kinds: [{
    ...bookingKindDefaults, name: 'desk',
    schedule: { mon: [{ start: '09:00', end: '10:00' }, { start: '09:30', end: '10:30' }] },
  }] }, 100, key => key)
  expect(issues['kinds.0.schedule']).toEqual(['connectC.validation.windowOverlap'])
})
