import type { Compliance, ComplianceBlocks, Regulated } from '../api/controls'

export const defaultCompliance: Compliance = {
  enabled: false, roles: [], retention: [], consent_purposes: [],
  break_glass: { enabled: false, roles: [], max_minutes: 60 },
  export_entities: [], export_fields: [], export_consent_purpose: null,
}
export const defaultRegulated: Regulated = { enabled: false, key_provider: 'file', fields: [] }

export type BlockDraft<T> = { draft: T; base: T; version: number; revision: number }
export type BlockAction<T> = { type: 'edit'; apply: (draft: T) => T } | { type: 'reset'; value: T; version: number }

export function blockDraftReducer<T extends ComplianceBlocks[keyof ComplianceBlocks]>(
  state: BlockDraft<T>, action: BlockAction<T>,
): BlockDraft<T> {
  if (action.type === 'reset') return { draft: action.value, base: action.value, version: action.version, revision: state.revision + 1 }
  return { ...state, draft: action.apply(state.draft) }
}
