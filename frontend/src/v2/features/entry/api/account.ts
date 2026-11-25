import { queryOptions } from '@tanstack/react-query'
import { api } from '../../../../api/client'
import type { ApiTokenInfo, MfaStatus } from '../../../../api/types'

export type { ApiTokenInfo, MfaStatus }
export const accountKeys = {
  mfa: () => ['entry', 'account-mfa'] as const,
  tokens: () => ['entry', 'account-tokens'] as const,
}

const queryDefaults = { staleTime: 15_000, retry: false, retryOnMount: false } as const

export const mfaOptions = queryOptions({
  ...queryDefaults, queryKey: accountKeys.mfa(), queryFn: api.mfaStatus,
})
export const tokenOptions = queryOptions({
  ...queryDefaults, queryKey: accountKeys.tokens(), queryFn: api.listApiTokens,
})

export const accountApi = {
  setDefaultOrganization: api.setDefaultOrg,
  setup: api.totpSetup,
  enable: api.totpEnable,
  disable: api.totpDisable,
  regenerate: api.regenerateRecoveryCodes,
  createToken: api.createApiToken,
  revokeToken: api.revokeApiToken,
  logoutEverywhere: api.logoutEverywhere,
}
