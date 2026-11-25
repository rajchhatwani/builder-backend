import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { useRef } from 'react'
import { api, saveBlob } from '../../../../api/client'
import type { OrgAiCost } from '../../../../api/types'
import { entryKeys } from './entry'
import { projectKeys } from './projects'

export type {
  Organization, UserAccount, OrgRole, OrgPlan, PlanInfo, OrgPolicies, OrgPoliciesUpdate,
  OrgInvitationCreated, OrgUsageMetric, OrgMember, SsoConfig, SsoConfigWrite, SsoProtocol,
  SsoCheck, ScimConfig, ScimRole, OrgAiSettingsWrite, OrgAiSettings, OrgAiCost,
} from '../../../../api/types'

const orgKey = (slug: string) => ['entry', 'org-console', slug] as const
const options = <T>(slug: string, key: string, queryFn: () => Promise<T>, page?: number) => queryOptions({
  queryKey: [...orgKey(slug), key, page], queryFn, retry: false, retryOnMount: false, staleTime: 15_000,
})

type AiCost = Omit<OrgAiCost, 'items'> & { items: (OrgAiCost['items'][number] & {
  run_id?: string | null; cache_read_tokens?: number; cache_write_tokens?: number
})[] }

export const orgQueries = {
  members: (slug: string) => options(slug, 'members', () => api.orgMembers(slug)),
  invites: (slug: string) => options(slug, 'invites', () => api.orgInvitations(slug)),
  projects: (slug: string) => options(slug, 'projects', () => api.orgProjects(slug)),
  policies: (slug: string) => options(slug, 'policies', () => api.orgPolicies(slug)),
  sso: (slug: string) => options(slug, 'sso', () => api.ssoConfig(slug)),
  scim: (slug: string) => options(slug, 'scim', () => api.scimConfig(slug)),
  audit: (slug: string, page: number) => options(slug, 'audit', () => api.orgAudit(slug, 50, (page - 1) * 50), page),
  aiSettings: (slug: string) => options(slug, 'ai-settings', () => api.orgAiSettings(slug)),
  aiCost: (slug: string, page: number) => options<AiCost>(slug, 'ai-cost', () => api.orgAiCost(slug, 20, (page - 1) * 20), page),
  usage: (slug: string) => options(slug, 'usage', () => api.orgUsage(slug)),
  registry: (slug: string) => options(slug, 'registry', () => api.orgRegistryProjects(slug)),
}

export const orgApi = {
  rename: api.renameOrg, remove: api.removeOrgMember, role: api.setOrgMemberRole,
  transfer: api.transferOrgOwnership, delete: api.deleteOrg, cancelDeletion: api.cancelOrgDeletion,
  invite: api.createOrgInvitation, resend: api.resendOrgInvitation, revoke: api.revokeOrgInvitation,
  createProject: api.createProject, joinProject: api.joinOrgProject, transferProject: api.transferOrgProject,
  checkout: api.startCheckout, portal: api.openBillingPortal, async export(slug: string) {
    const { blob, filename } = await api.exportOrg(slug)
    saveBlob(blob, filename)
  },
  policies: api.updateOrgPolicies,
  saveSso: api.saveSsoConfig, deleteSso: api.deleteSsoConfig, activateSso: api.activateSso,
  domain: api.addSsoDomain, verifyDomain: api.verifySsoDomain, removeDomain: api.removeSsoDomain,
  testSso: api.startSsoTest, checkSso: api.checkSso,
  scimToken: api.issueScimToken, scim: api.updateScim, deleteScim: api.deleteScim,
  aiSettings: api.updateOrgAiSettings, usageLimit: api.setOrgUsageLimit,
  defaultOrg: api.setDefaultOrg,
}

export function useOrgMutation(slug: string, userId: string) {
  const client = useQueryClient()
  const operation = useRef<(() => Promise<void>) | null>(null)
  const busy = useRef(false)
  const mutation = useMutation({
    mutationFn: async () => {
      // The mutation cache carries neither credentials nor one-time tokens.
      const run = operation.current
      operation.current = null
      await run?.()
    },
    retry: false, gcTime: 0, networkMode: 'always',
  })

  async function run(action: () => Promise<unknown>, refresh: 'org' | 'projects' | 'none' = 'org') {
    if (busy.current) return
    busy.current = true
    operation.current = async () => { await action() }
    try {
      await mutation.mutateAsync()
    } finally {
      busy.current = false
      if (refresh !== 'none') {
        void client.invalidateQueries({ queryKey: entryKeys.organizations(userId) })
        void client.invalidateQueries({ queryKey: orgKey(slug) })
        void client.invalidateQueries({ queryKey: projectKeys.plan(slug) })
      }
      if (refresh === 'projects') void client.invalidateQueries({ queryKey: projectKeys.lists() })
    }
  }
  return { ...mutation, run }
}
