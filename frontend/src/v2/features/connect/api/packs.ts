import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../../../api/client'
import { issuesFromDetail } from '../../../../forms/schemaLogic'
import type { PathErrors } from '../../../../forms/types'
import { getBlock, removeBlock, setBlock } from '../../../../shell/packs/packsLogic'
import { connectKeys } from './connect'

export type PackBlock = Record<string, unknown>
export type PackAddress = readonly [pack: 'money' | 'operations' | 'booking', block?: string]
type Packs = { money?: PackBlock | null; operations?: PackBlock | null; booking?: PackBlock | null; ai?: PackBlock | null }
type PacksRead = { packs: Packs | null; version: number; row_version: number; updated_at: string | null }

export function readPack(packs: Packs | null, address: PackAddress) {
  return getBlock(packs, ...address)
}

export function changePack(packs: Packs | null, address: PackAddress, value: PackBlock | null): Packs {
  if (value) return setBlock(packs, address[0], address[1], value)
  const result = removeBlock(packs, ...address)
  const [pack] = address
  // The backend materializes absent siblings as null in its response.
  const siblings = getBlock(result, pack)
  if (siblings && Object.values(siblings).every(value => value == null)) delete result[pack]
  return result
}

export const packsOptions = (id: string) => queryOptions({
  queryKey: connectKeys.block(id, 'packs'),
  queryFn: async () => await api.getBlock(id, 'packs') as PacksRead,
  retry: false, retryOnMount: false, staleTime: 15_000,
})

export function usePacksWrite(id: string) {
  const client = useQueryClient()
  const queryKey = packsOptions(id).queryKey
  return useMutation({
    scope: { id: 'connect-packs:' + id },
    mutationFn: async ({ packs, version }: { packs: Packs; version: number }) =>
      await api.putBlock(id, 'packs', { packs, expected_version: version }) as PacksRead,
    onSuccess: async data => {
      await client.cancelQueries({ queryKey, exact: true })
      client.setQueryData(queryKey, data)
      await client.invalidateQueries({ queryKey: ['projects', id], predicate: query =>
        !(query.queryKey.length === queryKey.length && queryKey.every((part, index) => part === query.queryKey[index])) })
    },
  })
}

export function packFieldErrors(error: unknown, address: PackAddress): PathErrors {
  if (!(error instanceof ApiError) || error.status !== 422) return {}
  const prefix = 'packs.' + address.join('.')
  const details = Object.entries(issuesFromDetail(error.details))
  for (const entry of error.details) {
    if (entry && typeof entry === 'object' && 'path' in entry && typeof entry.path === 'string' &&
      'message' in entry && typeof entry.message === 'string') {
      details.push([entry.path.replace(/\[(\d+)\]/g, '.$1'), [entry.message]])
    }
  }
  return Object.fromEntries(details
    .filter(([path]) => path === prefix || path.startsWith(prefix + '.'))
    .map(([path, messages]) => [path.slice(prefix.length + 1), messages]))
}
