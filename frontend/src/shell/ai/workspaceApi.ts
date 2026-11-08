import { ApiError } from '../../api/client'
import { BASE_URL, CSRF_HEADERS, authHeader, refreshSession } from '../../api/session'
import type { WsFile, WsFileContent } from './stageLogic'

async function call<T>(path: string, init: RequestInit = {}, retried = false): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...CSRF_HEADERS, ...authHeader('app'), ...init.headers },
  })
  if (res.status === 401 && !retried && (await refreshSession('app'))) return call<T>(path, init, true)
  let body: unknown = {}
  try { body = await res.json() } catch { if (res.ok) throw new ApiError(res.status, { code: 'bad_response', message: 'The server sent a response that could not be read', details: [] }) }
  if (!res.ok) {
    const raw = (body ?? {}) as { code?: string; message?: string; details?: unknown[] }
    throw new ApiError(res.status, { code: typeof raw.code === 'string' ? raw.code : 'bad_response', message: typeof raw.message === 'string' ? raw.message : `The server answered ${res.status}`, details: Array.isArray(raw.details) ? raw.details : [] })
  }
  return body as T
}

const W = (pid: string, wid: string) => `/projects/${pid}/workspaces/${wid}/files`
export const workspaceApi = {
  list: (pid: string, wid: string) => call<WsFile[]>(W(pid, wid)),
  read: (pid: string, wid: string, path: string) => call<WsFileContent>(`${W(pid, wid)}/content?path=${encodeURIComponent(path)}`),
  write: (pid: string, wid: string, path: string, content: string, expected_sha256: string) =>
    call<WsFileContent>(`${W(pid, wid)}/content`, { method: 'PUT', body: JSON.stringify({ path, content, expected_sha256 }) }),
  /** Issues a new preview token (the old one stops working). Returned once; the caller keeps it in memory only. */
  rotateToken: (pid: string, prid: string) => call<{ token: string }>(`/projects/${pid}/previews/${prid}/rotate-token`, { method: 'POST' }),
  getPreview: (pid: string, prid: string) => call<{ id: string; state: string; url_path: string }>(`/projects/${pid}/previews/${prid}`),
}
