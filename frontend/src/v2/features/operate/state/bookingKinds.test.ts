import { expect, it } from 'vitest'
import { bookingKinds, initialKinds } from './bookingKinds'

it('retains existing kind identities and unknown settings across insertions and removals', () => {
  const original = { name: 'desk', mode: 'range', extension: { notes: 'saved' } }
  const start = initialKinds([original])
  const added = bookingKinds(start, { type: 'add', mode: 'pool' })
  const removed = bookingKinds(added, { type: 'remove', id: 1 })
  const next = bookingKinds(removed, { type: 'add', mode: 'slot' })
  expect(next.items.map(item => item.id)).toEqual([0, 2])
  expect(next.items[0].original).toBe(original)
  expect(next.items[1].initial.mode).toBe('slot')
})
it('caps the draft at twenty kinds', () => {
  const start = initialKinds(Array.from({ length: 20 }, (_, i) => ({ name: 'resource' + i })))
  expect(bookingKinds(start, { type: 'add', mode: 'range' })).toBe(start)
})
