import type { IdentityProvider, IdpType } from '../../../../api/types'

export const oidcFields = ['issuer', 'authorization_url', 'token_url', 'jwks_url', 'userinfo_url'] as const
export type OidcField = typeof oidcFields[number]
export type ProviderRow = { key: number; value: IdentityProvider }
type ProviderState = { rows: ProviderRow[]; nextKey: number }
export type ProviderAction =
  | { type: 'add'; kind: IdpType; label: string }
  | { type: 'remove'; key: number }
  | { type: 'edit'; key: number; fields: Partial<IdentityProvider> }
  | { type: 'reset'; providers: IdentityProvider[] }

export function providerState(providers: IdentityProvider[]): ProviderState {
  return { rows: providers.map((value, key) => ({ key, value })), nextKey: providers.length }
}
export function providersReducer(state: ProviderState, action: ProviderAction): ProviderState {
  switch (action.type) {
    case 'add': {
      if (state.rows.length >= 10) return state
      const occupied = new Set(state.rows.map(row => row.value.alias.trim()))
      let alias: string = action.kind
      for (let count = 2; occupied.has(alias); count++) alias = action.kind + count
      const value: IdentityProvider = {
        type: action.kind, alias, display_name: action.label, client_id: '',
        tenant_id: null, hosted_domain: null, issuer: null, authorization_url: null, token_url: null,
        jwks_url: null, userinfo_url: null,
      }
      return { rows: [...state.rows, { key: state.nextKey, value }], nextKey: state.nextKey + 1 }
    }
    case 'remove': return { ...state, rows: state.rows.filter(row => row.key !== action.key) }
    case 'edit': return { ...state, rows: state.rows.map(row => row.key === action.key
      ? { ...row, value: { ...row.value, ...action.fields } } : row) }
    case 'reset': return providerState(action.providers)
  }
}
