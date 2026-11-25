import { expect, it } from 'vitest'
import { draftReducer } from './draft'

it('locks a draft to the first edited version and clears it explicitly', () => {
  const draft = draftReducer(null, { type: 'edit', value: ['new'], version: 7 })
  expect(draftReducer(draft, { type: 'edit', value: ['changed'], version: 9 })).toEqual({ value: ['changed'], version: 7 })
  expect(draftReducer(draft, { type: 'clear' })).toBeNull()
  expect(draftReducer(null, { type: 'edit', value: null, version: 9 })).toEqual({ value: null, version: 9 })
})
