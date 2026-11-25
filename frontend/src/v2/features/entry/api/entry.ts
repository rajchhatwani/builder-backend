import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef } from 'react'
import { api, ApiError } from '../../../../api/client'
import { accessToken, onSessionLost, refreshOutcome } from '../../../../api/session'
import { isMfaChallenge } from '../../../../api/types'
import type { LoginDiscovery, MfaChallenge, TotpSetup, UserAccount } from '../../../../api/types'

export type { LoginDiscovery, MfaChallenge, TotpSetup, UserAccount }
export type InvitationTarget = { by: 'id' | 'token'; value: string }

export const entryKeys = {
  session: () => ['entry', 'session'] as const,
  invitations: (userId: string) => ['entry', 'invitations', userId] as const,
  organizations: (userId: string) => ['entry', 'organizations', userId] as const,
  organization: (userId: string, slug: string) => [...entryKeys.organizations(userId), slug] as const,
}

export const sessionOptions = queryOptions({
  queryKey: entryKeys.session(),
  queryFn: async () => {
    if (!accessToken('app')) {
      const outcome = await refreshOutcome('app')
      if (outcome === 'lost') return null
      if (outcome === 'unavailable') throw new Error('session_unavailable')
    }
    return api.me()
  },
  staleTime: Infinity,
  retry: false,
  retryOnMount: false,
})

export function useCustomerSession(enabled = true) {
  return useQuery({ ...sessionOptions, enabled })
}

export function useSessionLoss() {
  const client = useQueryClient()
  useEffect(() => onSessionLost(surface => {
    if (surface !== 'app') return
    clearCustomerQueries(client)
  }), [client])
}

export function clearCustomerQueries(client: QueryClient) {
  const privateQueries = { predicate: (query: { queryKey: readonly unknown[] }) =>
    query.queryKey[0] !== 'entry' || query.queryKey[1] !== 'session' }
  void client.cancelQueries()
  client.setQueryData(entryKeys.session(), null)
  client.removeQueries(privateQueries)
}

export function useSetCustomer() {
  const client = useQueryClient()
  return (user: UserAccount | null) => client.setQueryData(entryKeys.session(), user)
}

export const invitationsOptions = (userId: string, verified: boolean) => queryOptions({
  queryKey: entryKeys.invitations(userId),
  queryFn: api.myPendingInvitations,
  enabled: verified,
  retry: false,
  retryOnMount: false,
  staleTime: 15_000,
})

export const organizationsOptions = (userId: string) => queryOptions({
  queryKey: entryKeys.organizations(userId), queryFn: api.listOrgs, retry: false, staleTime: 15_000,
})

export const organizationOptions = (userId: string, slug: string) => queryOptions({
  queryKey: entryKeys.organization(userId, slug), queryFn: () => api.getOrg(slug), retry: false,
})

export const entryApi = {
  discoverLogin: api.discoverLogin,
  async login(email: string, password: string) {
    const result = await api.login(email, password)
    return isMfaChallenge(result) ? { challenge: result } : { user: result.user }
  },
  loginMfa: api.loginMfa,
  register: api.register,
  verifyEmail: api.verifyEmail,
  resendVerification: api.resendVerification,
  changePassword: api.changePassword,
  logout: api.logout,
  async acceptInvitation(target: InvitationTarget) {
    return target.by === 'id' ? api.acceptInvitationById(target.value) : api.acceptInvitation(target.value)
  },
}

export function useEntryAction() {
  // Pass no credentials, tokens, or recovery codes through the mutation cache.
  const operation = useRef<(() => Promise<void>) | null>(null)
  const running = useRef(false)
  const mutation = useMutation({
    mutationFn: async () => {
      const run = operation.current
      operation.current = null
      try {
        if (!run) throw new Error('entry_action_missing')
        await run()
      } finally {
        running.current = false
      }
    },
    networkMode: 'always',
    retry: false,
    gcTime: 0,
  })
  const { mutate } = mutation
  const run = useCallback((action: () => Promise<void>) => {
    if (running.current) return
    running.current = true
    operation.current = action
    mutate()
  }, [mutate])
  return { ...mutation, run }
}

export function entryError(error: unknown) {
  if (!(error instanceof ApiError)) return { status: 0, code: '', message: '' }
  return { status: error.status, code: error.code, message: error.message, details: error.details }
}
