import { useNavigate, useParams, useSearch } from '@tanstack/react-router'
import type { SectionSearch } from '../../../projectNavigation'

type PreviewToolSearch = Pick<SectionSearch, 'role' | 'tool' | 'workbench' | 'preview'>

export function usePreviewToolSearch() {
  const navigate = useNavigate()
  const { projectId, section } = useParams({ strict: false })
  const pageSearch = useSearch({ from: '/projects/$projectId/$section', shouldThrow: false })
  const overviewSearch = useSearch({ from: '/projects/$projectId/overview', shouldThrow: false })
  return function update(patch: PreviewToolSearch) {
    if (!projectId) return
    const search = { ...overviewSearch, ...pageSearch, ...patch }
    if (section) void navigate({ to: '/projects/$projectId/$section', params: { projectId, section }, search })
    else void navigate({ to: '/projects/$projectId/overview', params: { projectId }, search })
  }
}
