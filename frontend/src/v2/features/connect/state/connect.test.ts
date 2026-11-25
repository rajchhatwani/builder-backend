import { expect, it } from 'vitest'
import { draftFrom, draftReducer } from './draft'
import { tokenReducer } from './token'

it('keeps edited fields independent of saved nested configuration', () => {
  const saved = draftFrom({ scale: { api_replicas: 1, pool_size: null }, currencies: ['JPY'] })
  const edit = draftReducer({}, { type: 'change', name: 'scale.api_replicas', value: '2' })
  expect({ ...saved, ...edit }).toEqual({ 'scale.api_replicas': '2', 'scale.pool_size': '', currencies: ['JPY'] })
  expect(draftReducer(edit, { type: 'replace', values: {} })).toEqual({})
  expect(saved['scale.api_replicas']).toBe('1')
})

it('forgets a revealed token on close and ignores a result if the flow has closed', () => {
  const opened = tokenReducer({ step: 'closed' }, { type: 'open' })
  const reveal = tokenReducer(opened, { type: 'created', token: 'one-time-value' })
  expect(reveal).toEqual({ step: 'reveal', token: 'one-time-value' })
  const closed = tokenReducer(reveal, { type: 'close' })
  expect(tokenReducer(closed, { type: 'created', token: 'late-value' })).toEqual({ step: 'closed' })
})
