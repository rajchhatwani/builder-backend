export type SectionDraft<T> = { version: number; rows: T[] } | null
export type SectionAction<T> =
  | { type: 'set'; version: number; rows: T[] }
  | { type: 'reset' }

export function sectionDraft<T>(state: SectionDraft<T>, action: SectionAction<T>): SectionDraft<T> {
  if (action.type === 'reset') return null
  return { version: state?.version ?? action.version, rows: action.rows }
}
