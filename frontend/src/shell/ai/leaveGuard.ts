import { useEffect, useRef, type MutableRefObject } from 'react'

export const LEAVE_MESSAGE = 'Discard your unsaved code changes and leave this view?'

/** True while the hash still points at the Build section of this project (a run switch inside it has its own prompt). */
export const isBuildHash = (hash: string, projectId: string) => hash.replace(/^#/, '').startsWith(`/p/${projectId}/build`) && /^\/p\/[^/]+\/build(?:[?/]|$)/.test(hash.replace(/^#/, ''))

/** Unsaved-code guard for leaving the Build section. A hash change cannot be cancelled, so a declined confirm puts the old hash back.
 *  Registered in the capture phase so it runs before the shell swaps the page. */
export function useLeaveBuildGuard(dirty: MutableRefObject<boolean>, projectId: string) {
  const last = useRef(typeof window === 'undefined' ? '' : window.location.hash)
  useEffect(() => {
    last.current = window.location.hash
    const onHash = () => {
      const next = window.location.hash
      if (next === last.current) return // our own revert
      if (dirty.current && !isBuildHash(next, projectId)) {
        if (!window.confirm(LEAVE_MESSAGE)) { window.location.hash = last.current; return }
        dirty.current = false
      }
      last.current = next
    }
    window.addEventListener('hashchange', onHash, true)
    return () => window.removeEventListener('hashchange', onHash, true)
  }, [dirty, projectId])
}
