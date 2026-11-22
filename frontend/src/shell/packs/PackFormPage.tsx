import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../../api/client'
import { defaultFor, issuesFromDetail, type JsonSchema } from '../../forms'
import { ConflictBanner, LoadFailed } from '../behavior/ui'
import { ConfigFormPage } from '../connect/ConfigFormPage'
import { PageHeader } from '../connect/BlockUi'
import { getBlock, removeBlock, setBlock, type Obj } from './packsLogic'

/** Backend 422 locations are body.packs.<pack>.<block>.<field>; the form's paths start at <field>. */
export function relocate(details: unknown[], pack: string, block?: string): unknown[] {
  const prefix = ['body', 'packs', pack, ...(block ? [block] : [])]
  return (details ?? []).map((d) => {
    const e = d as { loc?: unknown[] }
    const loc = Array.isArray(e?.loc) ? e.loc : []
    return prefix.every((p, i) => loc[i] === p) ? { ...e, loc: ['body', ...loc.slice(prefix.length)] } : d
  })
}

type Loaded = { packs: Obj; version: number }
type View = { s: 'loading' } | { s: 'error'; message: string } | { s: 'ready'; block: Obj | null }

const read = (r: Record<string, unknown>): Loaded => ({ packs: (r.packs as Obj | null) ?? {}, version: typeof r.version === 'number' ? r.version : 0 })

/** One sub-block of the `packs` spec section as a generated form (GET/PUT /behavior/packs). The endpoint holds the
 *  WHOLE packs object, so a save sends it back with only packs.<pack>.<block> replaced (or packs.<pack> when `block`
 *  is omitted, e.g. booking). An empty block means "off": an Enable button creates it with the schema defaults. */
export function PackFormPage({ projectId, pack, block, title, intro, schema }: {
  projectId: string
  pack: string
  block?: string
  title: string
  intro: string
  schema: JsonSchema
}) {
  const latest = useRef<Loaded>({ packs: {}, version: 0 })
  const [view, setView] = useState<View>({ s: 'loading' })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [conflict, setConflict] = useState(false)
  const [confirmOff, setConfirmOff] = useState(false)
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])

  const fetchAll = useCallback(async (): Promise<Loaded> => {
    const l = read(await api.getBlock(projectId, 'packs'))
    latest.current = l
    return l
  }, [projectId])

  const refresh = useCallback(async () => {
    setView({ s: 'loading' })
    setConflict(false)
    try {
      const l = await fetchAll()
      if (alive.current) setView({ s: 'ready', block: getBlock(l.packs, pack, block) })
    } catch (e) {
      if (alive.current) setView({ s: 'error', message: e instanceof Error ? e.message : 'Could not load' })
    }
  }, [fetchAll, pack, block])
  useEffect(() => { void refresh() }, [refresh])

  const put = useCallback(async (packs: Obj): Promise<Loaded> => {
    const l = read(await api.putBlock(projectId, 'packs', { packs, expected_version: latest.current.version }))
    latest.current = l
    return l
  }, [projectId])

  // The form's own load/save: flat block <-> whole packs object.
  const load = useCallback(async (): Promise<Obj> => {
    const l = await fetchAll()
    return { ...(getBlock(l.packs, pack, block) ?? {}), version: l.version }
  }, [fetchAll, pack, block])
  const save = useCallback(async (body: Obj): Promise<Obj> => {
    const { expected_version, ...value } = body
    // Keep the version the form loaded with, so a stale form is answered 409 by the backend.
    let l: Loaded
    try {
      l = read(await api.putBlock(projectId, 'packs', { packs: setBlock(latest.current.packs, pack, block, value), expected_version }))
    } catch (e) {
      throw e instanceof ApiError && e.status === 422 ? new ApiError(422, { code: e.code, message: e.message, details: relocate(e.details, pack, block) }) : e
    }
    latest.current = l
    return { ...(getBlock(l.packs, pack, block) ?? {}), version: l.version }
  }, [projectId, pack, block])

  async function change(next: (p: Obj) => Obj, done: (l: Loaded) => void) {
    setBusy(true)
    setMsg('')
    try {
      const l = await put(next(latest.current.packs))
      done(l)
    } catch (e) {
      if (!alive.current) return
      if (e instanceof ApiError && e.status === 409) setConflict(true)
      else if (e instanceof ApiError && e.status === 422) {
        const issues = Object.entries(issuesFromDetail(e.details)).map(([k, m]) => `${k ? `${k}: ` : ''}${m.join(' ')}`)
        setMsg([e.message, ...issues].join(' '))
      } else setMsg(e instanceof Error ? e.message : 'Could not save')
    } finally {
      if (alive.current) setBusy(false)
    }
  }

  if (view.s === 'loading') return (<><PageHeader title={title}>{intro}</PageHeader><p className="empty-state" role="status">Loading…</p></>)
  if (view.s === 'error') return (<><PageHeader title={title}>{intro}</PageHeader><LoadFailed what={title.toLowerCase()} message={view.message} onRetry={() => void refresh()} /></>)

  if (view.block === null) {
    const enable = () => change(
      (p) => setBlock(p, pack, block, (defaultFor(schema, schema) ?? {}) as Obj),
      (l) => setView({ s: 'ready', block: getBlock(l.packs, pack, block) ?? {} }),
    )
    return (
      <>
        <PageHeader title={title}>{intro}</PageHeader>
        {conflict && <ConflictBanner onReload={() => void refresh()} />}
        <div className="card empty-hero" data-testid="block-off">
          <h2>{title} is switched off</h2>
          <p>The spec has no settings for it, so nothing is generated. Switching it on saves the default settings, which you can then edit.</p>
          <button onClick={() => void enable()} disabled={busy}>{busy ? 'Switching on…' : `Switch on ${title.toLowerCase()}`}</button>
          {msg && <div role="alert" data-variant="danger" className="bh-alert">{msg}</div>}
        </div>
      </>
    )
  }

  const off = () => change(
    (p) => removeBlock(p, pack, block),
    () => { setConfirmOff(false); setView({ s: 'ready', block: null }) },
  )
  return (
    <>
      <ConfigFormPage title={title} intro={intro} flag={`${pack}-${block ?? 'pack'}`} schema={schema} load={load} save={save} versioned />
      <div className="card co-note" data-testid="switch-off">
        {conflict && <ConflictBanner onReload={() => void refresh()} />}
        {!confirmOff
          ? <button className="outline" onClick={() => setConfirmOff(true)}>Switch off {title.toLowerCase()}</button>
          : (
            <>
              <span>Remove these settings from the spec? Other packs are not touched.</span>{' '}
              <button onClick={() => void off()} disabled={busy}>{busy ? 'Switching off…' : 'Yes, switch off'}</button>{' '}
              <button className="outline" onClick={() => setConfirmOff(false)} disabled={busy}>Keep it on</button>
            </>
          )}
        {msg && <div role="alert" data-variant="danger" className="bh-alert">{msg}</div>}
      </div>
    </>
  )
}
