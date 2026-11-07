import { BASE_URL } from '../../api/session'

/** The preview proxy lives on the builder API origin: /previews/{id}/... authenticated by X-Preview-Token only. */
export const previewUrl = (previewId: string, path: string): string => `${BASE_URL}/previews/${encodeURIComponent(previewId)}${path.startsWith('/') ? path : `/${path}`}`
export const TOKEN_HEADER = 'X-Preview-Token'
export type PreviewFailure = 'gone' | 'token' | 'rate' | 'other'
export function classifyStatus(status: number): PreviewFailure {
  if (status === 410 || status === 404) return 'gone'
  if (status === 401 || status === 403) return 'token'
  if (status === 429) return 'rate'
  return 'other'
}
