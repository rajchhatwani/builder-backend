import type { TotpSetup } from '../api/entry'

export type MfaStep = 'setup' | 'disable' | 'regenerate'
export type AccountMfaState =
  | { step: 'idle' }
  | { step: MfaStep }
  | { step: 'scan'; setup: TotpSetup }
  | { step: 'codes'; codes: string[] }

type AccountMfaAction =
  | { type: 'start'; step: MfaStep }
  | { type: 'scan'; setup: TotpSetup }
  | { type: 'recovery'; codes: string[] }
  | { type: 'complete' }

export const idleMfa: AccountMfaState = { step: 'idle' }

export function accountMfaReducer(state: AccountMfaState, action: AccountMfaAction): AccountMfaState {
  switch (action.type) {
    case 'start': return state.step === 'idle' ? { step: action.step } : state
    case 'scan': return state.step === 'setup' ? { step: 'scan', setup: action.setup } : state
    case 'recovery': return state.step === 'scan' || state.step === 'regenerate' ? { step: 'codes', codes: action.codes } : state
    case 'complete': return idleMfa
  }
}
