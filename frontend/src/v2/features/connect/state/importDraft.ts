export type ImportDraft = { mapping: Record<string, string | null>; changed: boolean }
export type ImportDraftAction = { type: 'map'; field: string; header: string | null } |
  { type: 'reset'; mapping: Record<string, string> }

export function importDraftReducer(state: ImportDraft, action: ImportDraftAction): ImportDraft {
  if (action.type === 'reset') return { mapping: action.mapping, changed: false }
  return { mapping: { ...state.mapping, [action.field]: action.header }, changed: true }
}
