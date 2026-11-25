import { expect, it } from 'vitest'
import { importDraftReducer } from './importDraft'
import { initialGrant, scopeGrantReducer } from './scopeGrant'

it('preserves existing mapping columns when explicitly unmapping a field', () => {
  const mapping = { reference: 'Ref', name: 'Name' }
  const next = importDraftReducer({ mapping, changed: false }, { type: 'map', field: 'name', header: null })
  expect(next).toEqual({ mapping: { reference: 'Ref', name: null }, changed: true })
  expect(mapping.name).toBe('Name')
  expect(importDraftReducer(next, { type: 'reset', mapping })).toEqual({ mapping, changed: false })
})

it('keeps independent scope decisions across environment changes without adding duplicates', () => {
  const state = scopeGrantReducer(initialGrant, { type: 'scope', scope: 'Invoice', checked: true })
  const sandbox = scopeGrantReducer(state, { type: 'environment', environment: 'sandbox' })
  expect(scopeGrantReducer(sandbox, { type: 'scope', scope: 'Invoice', checked: true })).toEqual({
    environment: 'sandbox', picked: ['Invoice'],
  })
  expect(scopeGrantReducer(sandbox, { type: 'scope', scope: 'Invoice', checked: false }).picked).toEqual([])
})
