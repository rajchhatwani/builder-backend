import { intakeDocuments } from '../../../validators'
import type { ValidationIssue } from '../../../validators'

export type IntakeDraft = { prompt: string; files: File[]; fileErrors: ValidationIssue[] }
export const emptyDraft: IntakeDraft = { prompt: '', files: [], fileErrors: [] }

type DraftAction =
  | { type: 'prompt'; value: string }
  | { type: 'pick'; files: File[] }
  | { type: 'remove'; index: number }
  | { type: 'clear' }

export function intakeReducer(state: IntakeDraft, action: DraftAction): IntakeDraft {
  switch (action.type) {
    case 'prompt': return { ...state, prompt: action.value }
    case 'pick': {
      const { files, errors } = intakeDocuments(state.files, action.files)
      return { ...state, files, fileErrors: errors }
    }
    case 'remove': return { ...state, files: state.files.filter((_, index) => index !== action.index), fileErrors: [] }
    case 'clear': return emptyDraft
  }
}
