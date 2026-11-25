import { expect, it } from 'vitest'
import { scimDraft, scimMappings } from './scimMappings'
import { orgGroupName } from '../../../validators'

it('keeps row identifiers stable through adds and removals and resets to saved mappings', () => {
  const saved = { engineering: 'owner' } as const
  let draft = scimMappings(scimDraft(saved), { type: 'add' })
  draft = scimMappings(draft, { type: 'remove', id: 0 })
  draft = scimMappings(draft, { type: 'add' })
  expect(draft.rows.map(row => row.id)).toEqual([1, 2])
  expect(scimMappings(draft, { type: 'reset', mappings: saved })).toEqual(scimDraft(saved))
})

it('requires group names and catches case-insensitive duplicates', () => {
  expect(orgGroupName('', [])?.key).toBe('validation.required')
  expect(orgGroupName('Ops', ['ops', 'Ops'])?.key).toBe('validation.duplicateGroup')
  expect(orgGroupName('Ops', ['Ops', 'Support'])).toBeUndefined()
})
