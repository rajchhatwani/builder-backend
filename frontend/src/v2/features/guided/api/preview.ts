import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../../../../api/client'
import { BASE_URL } from '../../../../api/session'
import { previewBase } from '../../../../shell/ai/seeItLogic'
import { sendRequest } from '../../../../shell/workbench/sendRequest'
import type { Credential } from '../state/preview'
import { usePreviewCredentials } from '../components/PreviewCredentials'
import { deliveryApi, deliveryKeys } from './delivery'
import type { Preview } from './delivery'

export const previewDeadline = 90_000
export const previewKeys = {
  detail: (project: string, id: string) => [...deliveryKeys.previews(project), 'detail', id] as const,
  proxy: (id: string, revision: number) => ['guided', 'proxy', id, revision] as const,
}

export const previewOptions = (project: string, id: string) => queryOptions({
  queryKey: previewKeys.detail(project, id), queryFn: () => deliveryApi.getPreview(project, id),
  enabled: Boolean(id), retry: false, retryOnMount: false,
  refetchInterval: query => {
    const preview = query.state.data
    return preview && ['starting', 'stopping'].includes(preview.state) && Date.now() - Date.parse(preview.created_at) < previewDeadline ? 2000 : false
  },
})

export function proxyAddress(preview: Preview, path: string) {
  const expected = '/previews/' + encodeURIComponent(preview.id)
  if (!preview.is_preview || (preview.url_path !== expected && preview.url_path !== expected + '/')
    || !path.startsWith('/') || path.startsWith('//')) throw new Error('preview_path')
  const base = previewBase(BASE_URL, preview.url_path)
  const url = new URL(base + path, window.location.origin)
  const mount = new URL(base + '/', window.location.origin)
  if (url.origin !== mount.origin || !url.pathname.startsWith(mount.pathname)
    || /\\|%2f|%5c/i.test(url.pathname)) throw new Error('preview_path')
  return url
}

export async function previewRequest(preview: Preview, credential: Credential, method: string, path: string, body?: unknown) {
  const url = proxyAddress(preview, path)
  const reply = await sendRequest({
    url: url.href, origin: url.origin, method, body: body === undefined ? undefined : JSON.stringify(body),
    previewToken: credential.token, bearer: credential.bearer,
  })
  let json: unknown
  try { json = JSON.parse(reply.text) } catch { json = null }
  return { ...reply, json }
}

export async function previewJson<T>(preview: Preview, credential: Credential, path: string, method = 'GET', body?: unknown): Promise<T> {
  const reply = await previewRequest(preview, credential, method, path, body)
  if (reply.status < 200 || reply.status >= 300) {
    const raw = reply.json as { code?: string; message?: string; error?: { code?: string; message?: string } } | null
    throw new ApiError(reply.status, { code: raw?.code ?? raw?.error?.code ?? '', message: raw?.message ?? raw?.error?.message ?? '', details: [] })
  }
  return reply.json as T
}

export function usePreviewLifecycle(project: string) {
  const client = useQueryClient()
  const { dispatch } = usePreviewCredentials()
  return useMutation({
    scope: { id: 'guided-preview:' + project },
    mutationFn: async (action: { type: 'start'; workspace?: string } | { type: 'rotate' | 'stop'; id: string }) => {
      if (action.type === 'stop') {
        const preview = await deliveryApi.stopPreview(project, action.id)
        dispatch({ type: 'stop', id: action.id })
        return preview
      }
      const { token, ...preview } = action.type === 'start'
        ? await deliveryApi.createPreview(project, action.workspace)
        : await deliveryApi.rotatePreview(project, action.id)
      dispatch({ type: 'connect', id: preview.id, token })
      return preview
    },
    onSuccess: preview => { client.setQueryData(previewKeys.detail(project, preview.id), preview) },
    onSettled: () => client.invalidateQueries({ queryKey: deliveryKeys.previews(project), exact: true }),
  })
}
