import { useEffect, useState } from 'react'
import { ApiError } from '../../api/client'

/** `?run=<id>` inside the hash (#/p/<id>/build?run=<run>). */
export const runIdFromHash = (hash: string): string | null => hash.match(/[?&]run=([0-9a-fA-F-]{8,40})/)?.[1] ?? null
export const runLink = (projectId: string, section: 'build' | 'plan', runId: string) => `#/p/${projectId}/${section}?run=${runId}`

export function useRunParam(): string | null {
  const [id, setId] = useState(() => runIdFromHash(window.location.hash))
  useEffect(() => {
    const on = () => setId(runIdFromHash(window.location.hash))
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return id
}

const CODE_TEXT: Record<string, string> = {
  plan_empty: 'The plan is empty. Add at least one item before approving.',
  preview_quota: 'The preview limit for this project is reached. Stop a preview and try again.',
  file_changed: 'The file changed since you opened it. Reload it and try again.',
  approval_expired: 'This request has expired. The agent has to ask again.',
  approval_already_decided: 'Someone else already decided this request.',
  approval_forbidden: 'Your role may not do this. Ask a project owner.',
  run_finished: 'The run has already finished.',
}

/** Shows the server's code with its message; known codes get a plain sentence. Network failures say so. */
export function errMsg(e: unknown): string {
  if (e instanceof ApiError) {
    const known = CODE_TEXT[e.code]
    if (known) return `${known} (${e.code})`
    return e.code ? `${e.message} (${e.code})` : e.message
  }
  if (e instanceof TypeError) return 'Could not reach the server. Check your connection and try again.'
  return e instanceof Error ? e.message : 'Something went wrong'
}
