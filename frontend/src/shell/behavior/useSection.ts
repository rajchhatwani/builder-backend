import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { ValidationIssue } from '../../api/types'
import { clientErrors, issuesForSection, type FieldErrors, type SectionIssues } from './formLogic'

export interface SectionConfig<Row, Body> {
  key: 'settings' | 'sequences' | 'lists' | 'history' | 'hooks' | 'seed'
  /** Optional own client checks (default: formLogic.clientErrors). */
  check?: (rows: Row[]) => FieldErrors
  /** Optional own mapping of backend issues to rows/fields (default: issuesForSection). */
  mapIssues?: (issues: ValidationIssue[]) => SectionIssues
  load: (projectId: string) => Promise<{ version: number; items: Body[] }>
  save: (projectId: string, items: Body[], expectedVersion: number) => Promise<{ version: number; items: Body[] }>
  fromBody: (b: Body) => Row
  toBody: (r: Row) => Body
}

const NO_ISSUES: SectionIssues = { section: [], rows: {} }

export interface SectionState<Row, Body> {
  status: 'loading' | 'error' | 'ready'
  loadError: string
  rows: Row[]
  /** Bodies as last loaded or saved: issue indexes refer to these. */
  saved: Body[]
  version: number
  dirty: boolean
  saving: boolean
  conflict: boolean
  saveError: string
  savedNote: string
  issues: SectionIssues
  clientErrs: FieldErrors
}

/** Load / edit / save one behaviour section: whole-section PUT with expected_version, 409 handling,
 *  and the backend's /behavior/issues messages mapped by path. */
export function useSection<Row, Body>(
  projectId: string,
  cfg: SectionConfig<Row, Body>,
  /** The API keeps ONE version for all behaviour sections of a project: tell sibling editors about a save. */
  onSaved?: (oldVersion: number, newVersion: number) => void,
) {
  const [s, setS] = useState<SectionState<Row, Body>>({
    status: 'loading', loadError: '', rows: [], saved: [], version: 0, dirty: false, saving: false,
    conflict: false, saveError: '', savedNote: '', issues: NO_ISSUES, clientErrs: {},
  })
  const cfgRef = useRef(cfg)
  cfgRef.current = cfg
  const onSavedRef = useRef(onSaved)
  onSavedRef.current = onSaved
  const latest = useRef(s)
  latest.current = s

  const fetchIssues = useCallback(async () => {
    try {
      const all = (await api.getBehaviorIssues(projectId)).issues
      return cfgRef.current.mapIssues ? cfgRef.current.mapIssues(all) : issuesForSection(cfgRef.current.key, all)
    } catch {
      return NO_ISSUES
    }
  }, [projectId])

  const load = useCallback(async () => {
    setS((p) => ({ ...p, status: 'loading', conflict: false, saveError: '', savedNote: '' }))
    try {
      const [read, issues] = await Promise.all([cfgRef.current.load(projectId), fetchIssues()])
      setS((p) => ({
        ...p, status: 'ready', rows: read.items.map(cfgRef.current.fromBody), saved: read.items, version: read.version,
        dirty: false, conflict: false, issues, clientErrs: {},
      }))
    } catch (err) {
      setS((p) => ({ ...p, status: 'error', loadError: err instanceof Error ? err.message : 'Could not load' }))
    }
  }, [projectId, fetchIssues])

  useEffect(() => {
    void load()
  }, [load])

  /** Change the rows. `touched` = [rowIndex, fieldKey] of a plain edit (its backend message goes away);
   *  omit it for add/remove/reorder (all old messages are stale then). */
  const change = useCallback((rows: Row[], touched?: [number, string]) => {
    setS((p) => {
      let issues = p.issues
      if (!touched) issues = NO_ISSUES
      else if (p.issues.rows[touched[0]]?.fields[touched[1]]) {
        const row = p.issues.rows[touched[0]]
        const { [touched[1]]: _gone, ...rest } = row.fields
        issues = { ...p.issues, rows: { ...p.issues.rows, [touched[0]]: { ...row, fields: rest } } }
      }
      return { ...p, rows, dirty: true, issues, savedNote: '', saveError: '' }
    })
  }, [])

  const save = useCallback(async () => {
    const cur = latest.current
    const errs = cfgRef.current.check ? cfgRef.current.check(cur.rows) : clientErrors(cfgRef.current.key as 'settings' | 'sequences' | 'lists' | 'history', cur.rows)
    if (Object.keys(errs).length) {
      setS((p) => ({ ...p, clientErrs: errs, saveError: 'Fix the highlighted fields before saving.' }))
      return
    }
    setS((p) => ({ ...p, saving: true, clientErrs: {}, saveError: '', savedNote: '' }))
    try {
      const read = await cfgRef.current.save(projectId, cur.rows.map(cfgRef.current.toBody), cur.version)
      const issues = await fetchIssues()
      onSavedRef.current?.(cur.version, read.version)
      setS((p) => ({
        ...p, saving: false, saved: read.items, version: read.version, dirty: false, issues,
        savedNote: `Saved (version ${read.version}).`,
        // keep the user's rows (and keys): the server echoes them
      }))
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) setS((p) => ({ ...p, saving: false, conflict: true }))
      else setS((p) => ({ ...p, saving: false, saveError: err instanceof Error ? err.message : 'Could not save' }))
    }
  }, [projectId, fetchIssues])

  /** A sibling section saved: if nothing else happened since our version, follow it (our edits stay). */
  const adopt = useCallback((from: number, to: number) => {
    setS((p) => (p.version === from ? { ...p, version: to } : p))
  }, [])

  return { state: s, change, save, reload: load, adopt }
}
