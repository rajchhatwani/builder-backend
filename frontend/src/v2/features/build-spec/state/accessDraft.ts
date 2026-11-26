import type { AccessDiffRequest } from '../../../../api/types'

export type AccessDraft = { version: number; seq: number; edits: AccessDiffRequest } | null
export type AccessAction = { type: 'reset' } | { type: 'edit'; version: number; seq: number; edits: AccessDiffRequest }

export function accessDraft(state: AccessDraft, action: AccessAction): AccessDraft {
  return action.type === 'reset' ? null :
    { version: state?.version ?? action.version, seq: state?.seq ?? action.seq, edits: { ...state?.edits, ...action.edits } }
}
