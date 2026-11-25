import type { ParsedTrace } from '../../../../shell/traces/traceLogic'

export type TraceState = { draft: string; trace?: ParsedTrace; error?: string; reading: boolean }
export const initialTrace: TraceState = { draft: '', reading: false }
type Action =
  | { type: 'edit'; draft: string }
  | { type: 'file' }
  | { type: 'loaded'; draft: string; trace: ParsedTrace }
  | { type: 'failed'; error: string; draft?: string }
  | { type: 'clear' }

export function traceReducer(state: TraceState, action: Action): TraceState {
  switch (action.type) {
    case 'edit': return { ...state, draft: action.draft }
    case 'file': return { ...state, reading: true, error: undefined, trace: undefined }
    case 'loaded': return { draft: action.draft, trace: action.trace, reading: false }
    case 'failed': return { draft: action.draft ?? state.draft, error: action.error, reading: false }
    case 'clear': return initialTrace
  }
}
