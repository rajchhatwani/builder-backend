import { useCallback } from 'react'
import { api } from '../../api/client'
import type { JsonSchema } from '../../forms'
import { ConfigFormPage } from './ConfigFormPage'
import type { ReactNode } from 'react'

type Cfg = Record<string, unknown>

/** One spec block as an editable form, through its B2-11 endpoint (GET/PUT /behavior/{path}).
 *  The endpoint wraps the block (`{ jobs: {...}, version }`); the form works on the flat block, and the version is the
 *  section's optimistic-lock counter (sent back as `expected_version`; a stale one answers 409). */
export function BlockFormPage({ projectId, path, key_, title, intro, schema, status }: {
  projectId: string
  path: string
  key_: string
  title: string
  intro: string
  schema: JsonSchema
  status?: (c: Cfg) => ReactNode
}) {
  const load = useCallback(async (): Promise<Cfg> => {
    const r = await api.getBlock(projectId, path)
    return { ...((r[key_] as Cfg | null) ?? { enabled: false }), version: r.version }
  }, [projectId, path, key_])
  const save = useCallback(async (body: Cfg): Promise<Cfg> => {
    const { expected_version, ...block } = body
    const r = await api.putBlock(projectId, path, { [key_]: block, expected_version })
    return { ...((r[key_] as Cfg | null) ?? { enabled: false }), version: r.version }
  }, [projectId, path, key_])
  return <ConfigFormPage title={title} intro={intro} flag={path} schema={schema} load={load} save={save} versioned status={status} />
}
