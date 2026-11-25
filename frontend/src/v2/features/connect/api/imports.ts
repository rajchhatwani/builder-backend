import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, saveBlob } from '../../../../api/client'
import { authHeader, BASE_URL, notifySessionLost, refreshOutcome } from '../../../../api/session'
import type { ImportCommitResult, ImportCounts, ImportPreview, ImportRecordPage } from '../../../../api/types'
import { connectKeys } from './connect'

export type { ImportCommitResult, ImportPreview, ImportRow } from '../../../../api/types'
type Batch = {
  id: string; entity: string; filename: string; content_sha256: string; status: string
  mapping: Record<string, string>; counts: ImportCounts & { commit?: Pick<ImportCommitResult, 'created' | 'duplicate' | 'rejected'> }; created_at: string; committed_at: string | null
}
type BatchPage = { items: Batch[]; total: number; limit: number; offset: number }
const options = { retry: false, retryOnMount: false }
export const historySize = 20
export const recordSize = 20
export const reviewSize = 100

// The shared client does not expose batch reads, offsets for records, or download headers.
async function readImport(id: string, suffix: string, signal?: AbortSignal) {
  const send = () => fetch(BASE_URL + '/projects/' + encodeURIComponent(id) + '/imports' + suffix, {
    credentials: 'include', headers: authHeader('app'), signal,
  })
  let response = await send()
  if (response.status === 401) {
    const outcome = await refreshOutcome('app')
    if (outcome === 'ok') response = await send()
    if (outcome === 'lost') notifySessionLost('app')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new ApiError(response.status, {
      code: body?.code ?? 'bad_response', message: body?.message ?? '', details: Array.isArray(body?.details) ? body.details : [],
    })
  }
  return response
}

export const importHistoryOptions = (id: string, page: number) => queryOptions({
  ...options, queryKey: connectKeys.imports(id, 'history', page),
  queryFn: async ({ signal }): Promise<BatchPage> => (await readImport(id, '?limit=' + historySize + '&offset=' + (page - 1) * historySize, signal)).json(),
})
export const importBatchOptions = (id: string, batch: string) => queryOptions({
  ...options, queryKey: connectKeys.imports(id, 'batch', batch),
  queryFn: async ({ signal }): Promise<ImportPreview> => (await readImport(id, '/' + encodeURIComponent(batch), signal)).json(),
})
export const importRowsOptions = (id: string, batch: string, status: string, page: number) => queryOptions({
  ...options, queryKey: connectKeys.imports(id, 'rows', batch, status, page),
  queryFn: () => api.listImportRows(id, batch, status === 'all' ? undefined : status, reviewSize, (page - 1) * reviewSize),
})
export const importRecordsOptions = (id: string, entity: string, page: number) => queryOptions({
  ...options, queryKey: connectKeys.imports(id, 'records', entity, page),
  queryFn: async ({ signal }): Promise<ImportRecordPage> => page === 1 ? api.listImportRecords(id, entity, recordSize)
    : (await readImport(id, '/records?' + new URLSearchParams({
      entity, limit: String(recordSize), offset: String((page - 1) * recordSize),
    }), signal)).json(),
})
const resultKey = (id: string, batch: string) => connectKeys.imports(id, 'result', batch)

export function importResultOptions(id: string, batch: string) {
  return queryOptions({
    queryKey: resultKey(id, batch), enabled: false, queryFn: (): Promise<ImportCommitResult | null> => Promise.resolve(null),
  })
}

export type ImportAction =
  | { type: 'upload'; file: File; entity: string; mapping?: Record<string, string> }
  | { type: 'mapping'; batch: string; mapping: Record<string, string | null> }
  | { type: 'fix'; batch: string; row: string; values: Record<string, string> }
  | { type: 'commit' | 'cancel'; batch: string }

export function useImportAction(id: string) {
  const client = useQueryClient()
  return useMutation({
    scope: { id: 'import:' + id },
    mutationFn: async (action: ImportAction) => {
      switch (action.type) {
        case 'upload': return { preview: await api.uploadImport(id, action.file, action.entity, action.mapping) }
        case 'mapping': return { preview: await api.setImportMapping(id, action.batch, action.mapping) }
        case 'fix': return { row: await api.fixImportRow(id, action.batch, action.row, action.values) }
        case 'commit': return { result: await api.commitImport(id, action.batch) }
        case 'cancel': await api.cancelImport(id, action.batch); return {}
      }
    },
    onSuccess: async (data, action) => {
      const preview = data.preview
      const key = preview && importBatchOptions(id, preview.batch_id).queryKey
      if (key) {
        await client.cancelQueries({ queryKey: key, exact: true })
        client.setQueryData(key, preview)
      }
      if (data.result) client.setQueryData(resultKey(id, data.result.batch_id), data.result)
      if (action.type === 'commit' || action.type === 'cancel') {
        const batchKey = importBatchOptions(id, action.batch).queryKey
        await client.cancelQueries({ queryKey: batchKey, exact: true })
        client.setQueryData<ImportPreview>(batchKey, old => old ? {
          ...old, status: action.type === 'commit' ? 'committed' : 'cancelled',
        } : undefined)
      }
      if (action.type !== 'upload') await client.invalidateQueries({ queryKey: connectKeys.imports(id), predicate: ({ queryKey }) =>
        queryKey[4] !== 'result' && !(key && queryKey[4] === 'batch' && queryKey[5] === key[5]) })
      else await client.invalidateQueries({ queryKey: connectKeys.imports(id, 'history') })
    },
  })
}

export function importQuota(error: unknown) {
  if (!(error instanceof ApiError) || error.status !== 429 || error.code !== 'quota_exceeded') return
  const detail = error.details[0] as { metric?: unknown; limit?: unknown; used?: unknown; period_end?: unknown } | undefined
  return {
    metric: detail?.metric === 'imports.batches' ? 'batches' : 'rows',
    limit: typeof detail?.limit === 'number' ? detail.limit : undefined,
    used: typeof detail?.used === 'number' ? detail.used : undefined,
    reset: typeof detail?.period_end === 'string' ? detail.period_end.slice(0, 10) : '',
  }
}

export async function exportImportCsv(id: string, entity: string) {
  const response = await readImport(id, '/records/export.csv?' + new URLSearchParams({ entity }))
  const filename = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') ?? '')?.[1] ?? 'records.csv'
  saveBlob(await response.blob(), filename)
  return response.headers.get('X-Export-Truncated') === 'true'
}
