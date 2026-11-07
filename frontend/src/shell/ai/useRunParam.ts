import { useEffect, useState } from 'react'

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

export const errMsg = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong')
