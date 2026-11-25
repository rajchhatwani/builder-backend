export type TokenFlow = { step: 'closed' } | { step: 'create' } | { step: 'reveal'; token: string }
export type TokenAction = { type: 'open' } | { type: 'close' } | { type: 'created'; token: string }

export function tokenReducer(state: TokenFlow, action: TokenAction): TokenFlow {
  switch (action.type) {
    case 'open': return { step: 'create' }
    case 'close': return { step: 'closed' }
    case 'created': return state.step === 'create' ? { step: 'reveal', token: action.token } : state
  }
}
