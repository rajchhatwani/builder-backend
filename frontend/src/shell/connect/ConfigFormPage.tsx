import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ApiError } from '../../api/client'
import { SchemaForm, defaultFor, issuesFromDetail, validateValue, type JsonSchema, type PathErrors } from '../../forms'
import { setPageFlag, type PageFlag } from '../pageFlag'
import { ConflictBanner, LoadFailed, SaveBar } from '../behavior/ui'
import { PageHeader } from './BlockUi'

type Config = Record<string, unknown>

export interface ConfigFormProps {
  title: string
  intro: string
  schema: JsonSchema
  flag: PageFlag
  load: () => Promise<Config>
  save: (body: Config) => Promise<Config>
  /** The write body carries `expected_version` (optimistic locking) when the backend row has a `version`. */
  versioned?: boolean
  /** Shown above the form, from the loaded config (for example: switched on or off). */
  status?: (config: Config) => ReactNode
}

/** Keep only the properties the write schema knows (server-only fields such as id/created_at must not be sent back). */
export function pickWritable(schema: JsonSchema, config: Config): Config {
  const out: Config = {}
  for (const k of Object.keys(schema.properties ?? {})) if (k in config) out[k] = config[k]
  return out
}

type State =
  | { s: 'loading' }
  | { s: 'error'; message: string }
  | { s: 'ready' }

/** One backend config section as a generated form: load, edit with SchemaForm, save with the section's own PUT.
 *  422 messages from the backend are shown verbatim next to the fields; 409 means someone else saved first. */
export function ConfigFormPage({ title, intro, schema, flag, load, save, versioned, status }: ConfigFormProps) {
  const [state, setState] = useState<State>({ s: 'loading' })
  const [config, setConfig] = useState<Config>({})
  const [value, setValue] = useState<Config>({})
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [conflict, setConflict] = useState(false)
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [ext, setExt] = useState<PathErrors>({})
  // Payments and storage answer 404 until their settings were saved once: start from the schema's defaults.
  const [fresh, setFresh] = useState(false)
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true // StrictMode runs effects twice
    return () => { alive.current = false }
  }, [])

  const reload = useCallback(async () => {
    setState({ s: 'loading' })
    try {
      const c = await load()
      if (!alive.current) return
      setConfig(c)
      setValue(pickWritable(schema, c))
      setDirty(false)
      setConflict(false)
      setExt({})
      setError('')
      setNote('')
      setFresh(false)
      setState({ s: 'ready' })
    } catch (e) {
      if (!alive.current) return
      if (e instanceof ApiError && e.status === 404) {
        setConfig({})
        setValue((defaultFor(schema, schema) ?? {}) as Config)
        setDirty(false)
        setConflict(false)
        setExt({})
        setError('')
        setNote('')
        setFresh(true)
        setState({ s: 'ready' })
      } else setState({ s: 'error', message: e instanceof Error ? e.message : 'Could not load' })
    }
  }, [load, schema])
  useEffect(() => { void reload() }, [reload])

  const hints = useMemo(() => validateValue(schema, schema, value), [schema, value])

  async function onSave() {
    if (Object.keys(hints).length) {
      setError('Fix the highlighted fields before saving.')
      return
    }
    setSaving(true)
    setError('')
    setNote('')
    setExt({})
    try {
      const body: Config = { ...value, ...(versioned ? { expected_version: config.version ?? 0 } : {}) }
      const saved = await save(body)
      if (!alive.current) return
      setConfig(saved)
      setValue(pickWritable(schema, saved))
      setDirty(false)
      setFresh(false)
      setNote(versioned && typeof saved.version === 'number' ? `Saved (version ${saved.version}).` : 'Saved.')
    } catch (e) {
      if (!alive.current) return
      if (e instanceof ApiError && e.status === 409) setConflict(true)
      else if (e instanceof ApiError && e.status === 422) {
        setExt(issuesFromDetail(e.details))
        setError(e.message)
      } else setError(e instanceof Error ? e.message : 'Could not save')
    } finally {
      if (alive.current) setSaving(false)
    }
  }

  function classic() {
    setPageFlag(flag, 'classic')
    window.location.reload()
  }

  return (
    <>
      <PageHeader title={title}>{intro}</PageHeader>
      <div className="bh-actions">
        <button className="outline small" onClick={classic} data-testid="use-classic">Use the classic panel</button>
        <small className="muted">The classic panel stays available; both edit the same saved settings.</small>
      </div>
      {state.s === 'loading' && <p className="empty-state" role="status">Loading…</p>}
      {state.s === 'error' && <LoadFailed what={title.toLowerCase()} message={state.message} onRetry={() => void reload()} />}
      {state.s === 'ready' && (
        <>
          {fresh && <p className="muted" data-testid="config-fresh">Nothing has been saved here yet. The form shows the defaults; save to create the settings.</p>}
          {status && <div className="card co-note" data-testid="config-status">{status(config)}</div>}
          {conflict && <ConflictBanner onReload={() => void reload()} />}
          <SchemaForm
            schema={schema}
            value={value}
            onChange={(v) => { setValue(v as Config); setDirty(true); setNote(''); setExt({}) }}
            externalErrors={ext}
            idPrefix={`cf-${flag}`}
          />
          <SaveBar dirty={dirty || fresh} saving={saving} onSave={() => void onSave()} onDiscard={() => void reload()} note={note} error={error} />
        </>
      )}
    </>
  )
}
