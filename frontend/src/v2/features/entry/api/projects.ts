import { queryOptions } from '@tanstack/react-query'
import { api, ApiError } from '../../../../api/client'
import type { Organization, Project, QuotaDetail } from '../../../../api/types'

export type { Organization, Project, QuotaDetail }
export const projectPageSize = 12
const batchSize = 200

export const projectKeys = {
  lists: () => ['entry', 'projects'] as const,
  page: (page: number) => [...projectKeys.lists(), page] as const,
  all: () => [...projectKeys.lists(), 'all'] as const,
  health: (id: string, viewer: boolean) => ['entry', 'project-health', id, viewer] as const,
  details: (id: string) => ['entry', 'project-details', id] as const,
  members: (id: string) => ['entry', 'project-members', id] as const,
  plans: () => ['entry', 'project-plan'] as const,
  plan: (slug: string) => [...projectKeys.plans(), slug] as const,
}

const queryDefaults = { staleTime: 15_000, retry: false, retryOnMount: false } as const

export const projectPageOptions = (page: number) => queryOptions({
  ...queryDefaults, queryKey: projectKeys.page(page),
  queryFn: () => api.listProjects(projectPageSize, (page - 1) * projectPageSize),
})

export const allProjectsOptions = queryOptions({
  ...queryDefaults, queryKey: projectKeys.all(),
  queryFn: async ({ signal }) => {
    const first = await api.listProjects(batchSize)
    const items = [...first.items]
    for (let offset = batchSize; offset < first.total; offset += batchSize) {
      signal.throwIfAborted()
      items.push(...(await api.listProjects(batchSize, offset)).items)
    }
    return items
  },
})

export const projectHealthOptions = (id: string, viewer = false) => queryOptions({
  ...queryDefaults, queryKey: projectKeys.health(id, viewer),
  queryFn: async () => {
    if (!viewer) return api.validateProject(id)
    const status = await api.getProjectStatus(id)
    return { valid: status.issues.length === 0, issues: status.issues }
  },
})

export const projectMemberOptions = (id: string) => queryOptions({
  ...queryDefaults, queryKey: projectKeys.members(id), queryFn: () => api.listMembers(id), enabled: Boolean(id),
})

export const projectDetailOptions = (id: string) => queryOptions({
  ...queryDefaults, queryKey: projectKeys.details(id),
  queryFn: async () => {
    const [entities, auth, generations] = await Promise.allSettled([
      api.listEntities(id, 1), api.getAuthConfig(id), api.listGenerations(id, 1),
    ])
    return {
      entities: entities.status === 'fulfilled' ? entities.value.total : undefined,
      signIn: auth.status === 'fulfilled' ? Boolean(auth.value?.enabled)
        : auth.reason instanceof ApiError && auth.reason.status === 404 && auth.reason.message === 'auth config not found' ? false : undefined,
      generation: generations.status === 'fulfilled' ? generations.value.items[0] ?? null : undefined,
    }
  },
})

export const projectPlanOptions = (slug: string) => queryOptions({
  ...queryDefaults, queryKey: projectKeys.plan(slug), queryFn: () => api.orgPlan(slug), enabled: Boolean(slug),
})

export const projectsApi = { create: api.createProject, remove: api.deleteProject, createOrganization: api.createOrg }
