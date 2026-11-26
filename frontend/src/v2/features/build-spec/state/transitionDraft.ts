export type TransitionDraft = {
  from: string[]
  to?: string
  auto: boolean
  roles: string[]
  guard: string
}

export type TransitionAction =
  | { field: 'from'; value: string[] }
  | { field: 'to'; value: string }
  | { field: 'auto'; value: boolean }
  | { field: 'roles'; value: string[] }
  | { field: 'guard'; value: string }

export function transitionDraft(state: TransitionDraft, action: TransitionAction): TransitionDraft {
  return { ...state, [action.field]: action.value }
}
