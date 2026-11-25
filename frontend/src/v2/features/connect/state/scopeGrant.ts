type Environment = 'prod' | 'sandbox'
export type ScopeGrant = { environment: Environment; picked: string[] }
type GrantAction = { type: 'scope'; scope: string; checked: boolean } | { type: 'environment'; environment: Environment }

export const initialGrant: ScopeGrant = { environment: 'prod', picked: [] }
export function scopeGrantReducer(state: ScopeGrant, action: GrantAction): ScopeGrant {
  if (action.type === 'environment') return { ...state, environment: action.environment }
  const picked = state.picked.filter(scope => scope !== action.scope)
  return { ...state, picked: action.checked ? [...picked, action.scope] : picked }
}
