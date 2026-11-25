import type { ScimRole } from '../api/org'

type Mapping = { id: number; name: string; role: ScimRole }
type State = { rows: Mapping[]; nextId: number }
type Action =
  | { type: 'add' }
  | { type: 'remove'; id: number }
  | { type: 'reset'; mappings: Record<string, ScimRole> }

export function scimDraft(mappings: Record<string, ScimRole>): State {
  const rows = Object.entries(mappings).map(([name, role], id) => ({ id, name, role }))
  return { rows, nextId: rows.length }
}

export function scimMappings(state: State, action: Action): State {
  switch (action.type) {
    case 'add': return {
      rows: [...state.rows, { id: state.nextId, name: '', role: 'member' }], nextId: state.nextId + 1,
    }
    case 'remove': return { ...state, rows: state.rows.filter(row => row.id !== action.id) }
    case 'reset': return scimDraft(action.mappings)
  }
}
