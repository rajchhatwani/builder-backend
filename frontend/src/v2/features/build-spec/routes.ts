import { useNavigate, useParams, useSearch } from '@tanstack/react-router'
import type { SectionSearch } from '../../projectNavigation'
import { editorSectionRoute as route } from '../../patterns/editorLink'

export { route }

export function useBuildRoute() {
  const { projectId } = useParams({ from: route })
  const search = useSearch({ from: route })
  const navigate = useNavigate({ from: route })
  const update = (patch: Partial<SectionSearch>, replace = false) =>
    void navigate({ search: previous => ({ ...previous, ...patch }), replace })
  return { projectId, search, update }
}
