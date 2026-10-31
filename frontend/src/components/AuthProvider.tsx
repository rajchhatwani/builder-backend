import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { api } from '../api/client'
import { onSessionLost, setAccessToken, setViewingOnly } from '../api/session'
import {
  isMfaChallenge,
  type ImpersonationState,
  type MfaChallenge,
  type SessionResponse,
  type UserAccount,
} from '../api/types'
import { isViewingTab, receiveViewingToken } from '../api/viewing'

type AuthState =
  | { status: 'loading' }
  | { status: 'anon' }
  | { status: 'user'; user: UserAccount }
  /** A "view as" tab whose session ended or never received its token (§4.5). */
  | { status: 'viewing-ended' }

interface AuthApi {
  state: AuthState
  /** Resolves with a challenge when a second step is needed (§4.4); null when signed in. */
  signIn: (email: string, password: string) => Promise<MfaChallenge | null>
  /** Finish a sign-in whose second step returned a session. */
  completeSignIn: (session: SessionResponse) => void
  signUp: (email: string, password: string, name: string) => Promise<void>
  signOut: () => Promise<void>
  /** After a password change or profile update the server returns a fresh user. */
  setUser: (user: UserAccount) => void
  /** Set in a "view as" tab: who is looking, and whether changes are switched on (§4.5). */
  viewing: ImpersonationState | null
  setViewing: (state: ImpersonationState | null) => void
}

const AuthContext = createContext<AuthApi | null>(null)

export function useAuth(): AuthApi {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}

/** The signed-in user; only call below the gate in App.tsx, where one always exists. */
export function useUser(): UserAccount {
  const { state } = useAuth()
  if (state.status !== 'user') throw new Error('useUser needs a signed-in user')
  return state.user
}

/** Customer-app session. The admin console has its own, separate one (pages/admin). */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: 'loading' })
  const [viewing, setViewing] = useState<ImpersonationState | null>(null)

  useEffect(() => {
    let cancelled = false
    const viewingTab = isViewingTab()
    if (viewingTab) {
      // The operator's window hands over the viewing token; there is no cookie session to resume.
      setViewingOnly(true)
      // The hand-off happens once per tab. A reload has no token and nobody to ask again, so
      // say so at once instead of waiting for a reply that will not come. (A flag, not a secret.)
      const used = sessionStorage.getItem('builder-viewing-used') === '1'
      ;(used ? Promise.resolve(null) : receiveViewingToken())
        .then(async (token) => {
          if (!token) return null
          sessionStorage.setItem('builder-viewing-used', '1')
          setAccessToken('app', token)
          const [user, info] = await Promise.all([api.me(), api.impersonationState()])
          return { user, info }
        })
        .then((found) => {
          if (cancelled) return
          if (!found) return setState({ status: 'viewing-ended' })
          setViewing(found.info)
          setState({ status: 'user', user: found.user })
          window.location.hash = '#/'
        })
        .catch(() => !cancelled && setState({ status: 'viewing-ended' }))
    } else {
      api.resume().then((user) => {
        if (!cancelled) setState(user ? { status: 'user', user } : { status: 'anon' })
      })
    }
    const stop = onSessionLost((surface) => {
      if (surface !== 'app') return
      setViewing(null)
      setState(viewingTab ? { status: 'viewing-ended' } : { status: 'anon' })
    })
    return () => {
      cancelled = true
      stop()
    }
  }, [])

  const signIn = useCallback(async (email: string, password: string) => {
    const result = await api.login(email, password)
    if (isMfaChallenge(result)) return result
    setState({ status: 'user', user: result.user })
    return null
  }, [])

  const completeSignIn = useCallback((session: SessionResponse) => {
    setState({ status: 'user', user: session.user })
  }, [])

  const signUp = useCallback(async (email: string, password: string, name: string) => {
    const session = await api.register({ email, password, name })
    setState({ status: 'user', user: session.user })
  }, [])

  const signOut = useCallback(async () => {
    await api.logout().catch(() => undefined)
    setState({ status: 'anon' })
    window.location.hash = '#/'
  }, [])

  const setUser = useCallback((user: UserAccount) => setState({ status: 'user', user }), [])

  const value = useMemo(
    () => ({ state, signIn, completeSignIn, signUp, signOut, setUser, viewing, setViewing }),
    [state, signIn, completeSignIn, signUp, signOut, setUser, viewing],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
