import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../../../../api/client'
import type { DocumentTemplate, DocumentsWrite } from '../../../../api/types'
import { operateKeys } from './operate'

export type { DocumentTemplate, DocumentsSettings, DocumentsWrite, LibraryTemplate } from '../../../../api/types'
const options = <T>(id: string, name: string, queryFn: () => Promise<T>) => queryOptions({
  queryKey: operateKeys.item(id, 'documents', name), queryFn, retry: false, retryOnMount: false,
})
export const documentsOptions = (id: string) => options(id, 'settings', () => api.getDocuments(id))
export const libraryOptions = (id: string) => options(id, 'library', () => api.documentsLibrary(id))
export const documentIssuesOptions = (id: string) => options(id, 'issues', () => api.documentsIssues(id))
export const documentSpecOptions = (id: string) => options(id, 'spec', async () => {
  const spec = await api.getSpecForPolicies(id)
  return spec as typeof spec & { auth: (NonNullable<typeof spec.auth> & { enabled?: boolean }) | null }
})

export function useSaveDocuments(id: string) {
  const cache = useQueryClient()
  return useMutation({
    mutationFn: (body: DocumentsWrite) => api.putDocuments(id, body),
    onSuccess: async result => {
      const key = documentsOptions(id).queryKey
      await cache.cancelQueries({ queryKey: key, exact: true })
      cache.setQueryData(key, result)
      void cache.invalidateQueries({ queryKey: ['projects', id], predicate: query => query.queryKey.join('/') !== key.join('/') })
    },
  })
}

export function usePdfPreview(id: string) {
  return useMutation({
    mutationFn: (body: { template: DocumentTemplate['template']; data: Record<string, unknown>; compute: string | null }) =>
      api.previewDocument(id, body),
  })
}

type DocumentPack = { kinds: { name: string; fields: { name: string; required: boolean }[] }[]; max_text_chars: number; review_below_bp: number }
export const documentPacksOptions = (id: string) => options(id, 'packs', async () =>
  await api.getBlock(id, 'packs') as { packs: { ai?: { documents?: DocumentPack | null } } | null })
