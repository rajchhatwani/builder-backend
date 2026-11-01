import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { ValidationIssue } from '../../api/types'
import type { SpecBlocks } from './specTypes'

export type SpecLoad =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; spec: SpecBlocks; issues: ValidationIssue[] }

/** Loads the spec and the backend validator's issues (a failing validator only empties the issue list). */
export function useSpecBlocks(projectId: string): { load: SpecLoad; reload: () => void } {
  const [load, setLoad] = useState<SpecLoad>({ status: 'loading' })
  const [n, setN] = useState(0)
  const reload = useCallback(() => {
    setLoad({ status: 'loading' })
    setN((v) => v + 1)
  }, [])
  useEffect(() => {
    let live = true
    Promise.all([api.getSpecBlocks(projectId), api.validateProject(projectId).then((r) => r.issues).catch(() => [] as ValidationIssue[])])
      .then(([spec, issues]) => live && setLoad({ status: 'ready', spec: spec ?? {}, issues }))
      .catch((e: unknown) => live && setLoad({ status: 'error', message: e instanceof Error ? e.message : 'Could not load the spec' }))
    return () => {
      live = false
    }
  }, [projectId, n])
  return { load, reload }
}
