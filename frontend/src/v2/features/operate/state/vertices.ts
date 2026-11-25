import type { Coordinates } from '../api/tools'

type Vertex = { id: number; point?: Coordinates }
export type Vertices = { nextId: number; items: Vertex[] }
export type VertexAction = { type: 'add' } | { type: 'remove'; id: number } | { type: 'move'; id: number; direction: -1 | 1 }
export const initialVertices = (points?: Coordinates[] | null): Vertices => ({
  nextId: points?.length ?? 3,
  items: points ? points.map((point, id) => ({ id, point })) : [{ id: 0 }, { id: 1 }, { id: 2 }],
})
export function vertices(state: Vertices, action: VertexAction): Vertices {
  if (action.type === 'add') return { nextId: state.nextId + 1, items: [...state.items, { id: state.nextId }] }
  if (action.type === 'remove') return { ...state, items: state.items.filter(item => item.id !== action.id) }
  const from = state.items.findIndex(item => item.id === action.id)
  const to = from + action.direction
  if (from < 0 || to < 0 || to >= state.items.length) return state
  const items = [...state.items]
  const [item] = items.splice(from, 1)
  items.splice(to, 0, item)
  return { ...state, items }
}
