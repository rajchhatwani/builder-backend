import { expect, it } from 'vitest'
import { initialVertices, vertices } from './vertices'

it('preserves vertex identities when the user moves, deletes, and adds points', () => {
  const initial = initialVertices()
  const moved = vertices(initial, { type: 'move', id: 2, direction: -1 })
  const removed = vertices(moved, { type: 'remove', id: 1 })
  const added = vertices(removed, { type: 'add' })
  expect(initial.items.map(item => item.id)).toEqual([0, 1, 2])
  expect(added.items.map(item => item.id)).toEqual([0, 2, 3])
})
