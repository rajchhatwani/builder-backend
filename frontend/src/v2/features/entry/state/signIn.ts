import type { LoginDiscovery, MfaChallenge, UserAccount } from '../api/entry'

type State =
  | { step: 'email'; email: string }
  | { step: 'password'; email: string }
  | { step: 'sso'; email: string; url: string; organization?: string }
  | { step: 'mfa'; email: string; challenge: MfaChallenge }
  | { step: 'recovery'; email: string; user: UserAccount; codes: string[] }

type Action =
  | { type: 'discovered'; email: string; result: LoginDiscovery }
  | { type: 'password' }
  | { type: 'challenge'; challenge: MfaChallenge }
  | { type: 'recovery'; user: UserAccount; codes: string[] }
  | { type: 'reset' }

export const initialSignIn: State = { step: 'email', email: '' }

export function signInReducer(state: State, action: Action): State {
  switch (action.type) {
    case 'discovered': {
      const { email, result } = action
      if (result.method === 'sso' && result.login_url) {
        try {
          const url = new URL(result.login_url)
          if (url.protocol === 'https:' || url.protocol === 'http:') {
            return { step: 'sso', email, url: url.href, organization: result.organization_name ?? undefined }
          }
        } catch { /* An unusable SSO URL leaves password sign-in available. */ }
      }
      return { step: 'password', email }
    }
    case 'password': return state.step === 'sso' ? { step: 'password', email: state.email } : state
    case 'challenge': return state.step === 'password' ? { step: 'mfa', email: state.email, challenge: action.challenge } : state
    case 'recovery': return state.step === 'mfa' ? { step: 'recovery', email: state.email, user: action.user, codes: action.codes } : state
    case 'reset': return initialSignIn
  }
}
