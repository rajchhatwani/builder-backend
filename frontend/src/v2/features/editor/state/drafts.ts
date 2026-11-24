export type Draft = { content: string; original: string; sha: string }
type Drafts = Record<string, Draft>
export type DraftAction =
  | { type: 'edit'; key: string; content: string; original: string; sha: string }
  | { type: 'clear'; key: string }

export function draftReducer(state: Drafts, action: DraftAction): Drafts {
  const draft = state[action.key]
  if (action.type === 'edit') {
    const original = draft?.original ?? action.original
    if (action.content !== original) {
      return { ...state, [action.key]: { content: action.content, original, sha: draft?.sha ?? action.sha } }
    }
  }
  return Object.fromEntries(Object.entries(state).filter(([key]) => key !== action.key))
}
