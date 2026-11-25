export type Draft<T> = { value: T; version: number } | null
export type DraftAction<T> = { type: 'edit'; value: T; version: number } | { type: 'clear' }

export function draftReducer<T>(draft: Draft<T>, action: DraftAction<T>): Draft<T> {
  if (action.type === 'clear') return null
  return { value: action.value, version: draft?.version ?? action.version }
}
