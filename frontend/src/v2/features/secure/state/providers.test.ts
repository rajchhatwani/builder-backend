import { expect, it } from 'vitest'
import { providersReducer, providerState } from './providers'

it('assigns distinct aliases and updates the intended row after another row is removed', () => {
  const add = { type: 'add', kind: 'oidc', label: 'OpenID Connect' } as const
  let state = providersReducer(providerState([]), add)
  state = providersReducer(state, add)
  expect(state.rows.map(row => row.value.alias)).toEqual(['oidc', 'oidc2'])
  state = providersReducer(state, { type: 'remove', key: 0 })
  state = providersReducer(state, { type: 'edit', key: 1, fields: { issuer: 'https://issuer.example.test' } })
  state = providersReducer(state, add)
  expect(state.rows.map(row => [row.key, row.value.alias, row.value.issuer])).toEqual([
    [1, 'oidc2', 'https://issuer.example.test'], [2, 'oidc', null],
  ])
})

it('limits the draft to ten providers', () => {
  let state = providerState([])
  for (let count = 0; count < 11; count++) {
    state = providersReducer(state, { type: 'add', kind: 'google', label: 'Google' })
  }
  expect(state.rows).toHaveLength(10)
})
