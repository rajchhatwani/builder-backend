import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../../../api/client'

export const projectKeys = {
  all: ['projects'] as const,
  project: (projectId: string) => [...projectKeys.all, projectId] as const,
  status: (projectId: string) => [...projectKeys.project(projectId), 'status'] as const,
}

export function statusOptions(projectId: string) {
  return queryOptions({
    queryKey: projectKeys.status(projectId),
    queryFn: () => api.getProjectStatus(projectId),
    staleTime: 30_000,
    retry: false,
    retryOnMount: false,
  })
}

export function useProjectStatus(projectId: string) {
  return useQuery({ ...statusOptions(projectId), enabled: Boolean(projectId) })
}

export function useStepMutation(projectId: string) {
  const client = useQueryClient()
  const key = projectKeys.status(projectId)
  return useMutation({
    scope: { id: `project-status:${projectId}` },
    mutationFn: async ({ step, restore }: { step: string; restore: boolean }) => {
      await client.cancelQueries({ queryKey: key })
      return restore ? api.undoDismissStep(projectId, step) : api.dismissStep(projectId, step)
    },
    onSuccess: data => {
      client.setQueryData(key, data)
      return client.invalidateQueries({ queryKey: key })
    },
  })
}

export function statusCode(error: unknown) {
  return error instanceof ApiError ? error.status : undefined
}
