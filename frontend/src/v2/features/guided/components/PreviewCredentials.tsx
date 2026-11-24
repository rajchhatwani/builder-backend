import { createContext, useContext, useReducer } from 'react'
import type { Dispatch, ReactNode } from 'react'
import { credentialsReducer } from '../state/preview'
import type { CredentialAction, Credentials } from '../state/preview'

const Context = createContext<{ credentials: Credentials; dispatch: Dispatch<CredentialAction> }>({ credentials: {}, dispatch: () => {} })

export function PreviewCredentials({ children }: { children: ReactNode }) {
  const [credentials, dispatch] = useReducer(credentialsReducer, {})
  return <Context.Provider value={{ credentials, dispatch }}>{children}</Context.Provider>
}

export function usePreviewCredentials() {
  return useContext(Context)
}
