import type { Path } from '../../forms/schemaLogic'
import type { PathErrors } from '../../forms/types'
import { changeSchemaValue } from './schemaValue'

export type SchemaDraft = {
  draft?: { value: unknown; version: number }
  touched: string[]
  submitted: boolean
  serverErrors: PathErrors
  revision: number
}
export const initialSchemaDraft: SchemaDraft = { touched: [], submitted: false, serverErrors: {}, revision: 0 }

type Action =
  | { type: 'edit'; path: Path; next: unknown; base: unknown; version: number }
  | { type: 'touch' | 'structure'; path: string }
  | { type: 'submit' }
  | { type: 'errors'; errors: PathErrors }
  | { type: 'reset' }

export function schemaDraftReducer(state: SchemaDraft, action: Action): SchemaDraft {
  switch (action.type) {
    case 'edit': {
      const draft = state.draft ?? { value: action.base, version: action.version }
      const path = action.path.join('.')
      const serverErrors = Object.fromEntries(Object.entries(state.serverErrors).filter(([key]) => key !== path && !key.startsWith(path + '.')))
      return { ...state, draft: { ...draft, value: changeSchemaValue(draft.value, action.path, action.next) }, serverErrors }
    }
    case 'touch':
      return state.touched.includes(action.path) ? state : { ...state, touched: [...state.touched, action.path] }
    case 'structure':
      return { ...state, touched: state.touched.filter(path => !path.startsWith(action.path + '.')) }
    case 'submit':
      return { ...state, submitted: true }
    case 'errors':
      return { ...state, serverErrors: action.errors }
    case 'reset':
      return { ...initialSchemaDraft, revision: state.revision + 1 }
  }
}

export function shownErrors(state: SchemaDraft, issues: PathErrors): PathErrors {
  return {
    ...Object.fromEntries(Object.entries(issues).filter(([path]) => state.submitted || state.touched.includes(path))),
    ...state.serverErrors,
  }
}
