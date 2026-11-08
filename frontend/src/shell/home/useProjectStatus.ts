import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'

export const statusKey = (projectId: string) => ['project-status', projectId] as const

/** One cache entry per project: the rail badges and the Home board read the same status call. */
export function useProjectStatus(projectId: string, enabled = true) {
  return useQuery({ queryKey: statusKey(projectId), queryFn: () => api.getProjectStatus(projectId), enabled })
}
