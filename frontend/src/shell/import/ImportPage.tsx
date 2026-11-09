import { useCallback, useEffect, useId, useMemo, useState } from 'react'
import { ApiError, api } from '../../api/client'
import type { ImportCommitResult, ImportCounts, ImportPreview, ImportRecord, ImportRow } from '../../api/types'
import { link } from '../../components/Sidebar'
import {
  STEPS, applyRowSave, changedValues, deriveStep, entitiesOf, fixableFields, groupErrors, initialMapping, mappingBody,
  quotaMessage, readyCount, startValue, summarise,
} from './importLogic'
import type { SpecEntity } from './importLogic'

type Load = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; entities: SpecEntity[] }

const msg = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback)

export function ImportPage({ projectId }: { projectId: string }) {
  const [load, setLoad] = useState<Load>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoad({ status: 'loading' })
    api
      .getSpecJson(projectId)
      .then((spec) => {
        if (!cancelled) setLoad({ status: 'ready', entities: entitiesOf(spec) })
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoad({ status: 'error', message: msg(err, 'Could not load the project') })
      })
    return () => {
      cancelled = true
    }
  }, [projectId, attempt])

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Import data</h1>
          <p>Bring a CSV file into one of your entities. You see what will be created, fix the rows that do not fit, and only then commit.</p>
        </div>
      </div>
      {load.status === 'loading' && <p className="empty-state">Loading…</p>}
      {load.status === 'error' && (
        <div className="card empty-hero" role="alert">
          <h2>We could not load this page</h2>
          <p>{load.message}</p>
          <button onClick={() => setAttempt((n) => n + 1)}>Try again</button>
        </div>
      )}
      {load.status === 'ready' && load.entities.length === 0 && (
        <div className="card empty-hero" data-testid="import-empty">
          <h2>No entities yet</h2>
          <p>Data is imported into an entity. Add one first, then come back with your file.</p>
          <a className="button" href={link(`/p/${projectId}/model`)}>
            Open the data model
          </a>
        </div>
      )}
      {load.status === 'ready' && load.entities.length > 0 && <Wizard projectId={projectId} entities={load.entities} />}
    </>
  )
}

function Wizard({ projectId, entities }: { projectId: string; entities: SpecEntity[] }) {
  const [entityName, setEntityName] = useState(entities[0].name)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [counts, setCounts] = useState<ImportCounts | null>(null)
  const [rows, setRows] = useState<ImportRow[]>([])
  const [reviewing, setReviewing] = useState(false)
  const [result, setResult] = useState<ImportCommitResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const entityId = useId()
  const fileId = useId()

  const entity = entities.find((e) => e.name === entityName) ?? entities[0]
  const step = deriveStep({ preview, reviewing, done: result !== null })
  const stepIndex = STEPS.findIndex((s) => s.id === step)

  const adopt = (p: ImportPreview) => {
    setPreview(p)
    setMapping(initialMapping(p))
    setCounts(p.counts)
    setRows(p.rejected)
  }

  const upload = async () => {
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      adopt(await api.uploadImport(projectId, file, entity.name))
    } catch (err) {
      setError(msg(err, 'Could not read that file'))
    } finally {
      setBusy(false)
    }
  }

  const changeMapping = async (field: string, header: string) => {
    if (!preview) return
    setBusy(true)
    setError(null)
    try {
      adopt(await api.setImportMapping(projectId, preview.batch_id, mappingBody(entity.fields, mapping, field, header)))
    } catch (err) {
      setError(msg(err, 'Could not change the mapping'))
    } finally {
      setBusy(false)
    }
  }

  const startReview = async () => {
    if (!preview) return
    setBusy(true)
    setError(null)
    try {
      const page = await api.listImportRows(projectId, preview.batch_id, 'rejected')
      setRows(page.items)
      setReviewing(true)
    } catch (err) {
      setError(msg(err, 'Could not load the rows that need fixing'))
    } finally {
      setBusy(false)
    }
  }

  const saveRow = useCallback(
    async (row: ImportRow, edits: Record<string, string>) => {
      if (!preview || !counts) return
      const values = changedValues(edits, row, mapping)
      if (Object.keys(values).length === 0) return
      const saved = await api.fixImportRow(projectId, preview.batch_id, row.id, values)
      if (saved.status === 'fixed') {
        setCounts(applyRowSave(counts, saved))
        setRows((all) => all.filter((r) => r.id !== row.id))
      } else {
        setRows((all) => all.map((r) => (r.id === row.id ? saved : r)))
      }
    },
    [preview, counts, mapping, projectId],
  )

  const commit = async () => {
    if (!preview) return
    setBusy(true)
    setError(null)
    try {
      setResult(await api.commitImport(projectId, preview.batch_id))
    } catch (err) {
      setError(err instanceof ApiError && err.status === 429 && err.code === 'quota_exceeded' ? quotaMessage(err.details) : msg(err, 'Could not commit the import'))
    } finally {
      setBusy(false)
    }
  }

  const startOver = async () => {
    if (preview && !result) await api.cancelImport(projectId, preview.batch_id).catch(() => undefined)
    setPreview(null)
    setFile(null)
    setRows([])
    setCounts(null)
    setReviewing(false)
    setResult(null)
    setError(null)
  }

  return (
    <div className="card">
      <ol aria-label="Import steps" className="import-steps">
        {STEPS.map((s, i) => (
          <li key={s.id} aria-current={i === stepIndex ? 'step' : undefined}>
            {i + 1}. {s.label}
          </li>
        ))}
      </ol>
      {error && (
        <div role="alert" data-testid="import-error">
          {error}
        </div>
      )}

      {step === 'choose' && (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void upload()
          }}
        >
          <p>
            <label htmlFor={entityId}>Entity</label>{' '}
            <select id={entityId} value={entity.name} onChange={(e) => setEntityName(e.target.value)}>
              {entities.map((e) => (
                <option key={e.name} value={e.name}>
                  {e.name}
                </option>
              ))}
            </select>
          </p>
          <p>
            <label htmlFor={fileId}>CSV file</label>{' '}
            <input id={fileId} type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </p>
          <button type="submit" disabled={!file || busy}>
            {busy ? 'Reading…' : 'Upload and preview'}
          </button>
        </form>
      )}

      {step === 'mapping' && preview && counts && (
        <section aria-label="Match columns">
          <div role="status" aria-live="polite" data-testid="import-summary">
            {summarise(counts)}
          </div>
          <p>Pick which column of your file feeds each field. Changing a column checks every row again and discards the fixes you made to rows.</p>
          <div className="table-scroll" tabIndex={0} role="region" aria-label="Column mapping table">
            <table>
              <caption>Columns for {preview.entity}</caption>
              <thead>
                <tr>
                  <th scope="col">Field</th>
                  <th scope="col">Column in your file</th>
                </tr>
              </thead>
              <tbody>
                {entity.fields.map((f) => (
                  <tr key={f.name}>
                    <th scope="row">
                      {f.name}
                      {f.required ? ' (required)' : ''}
                    </th>
                    <td>
                      <MappingSelect field={f.name} headers={preview.headers} value={mapping[f.name] ?? ''} disabled={busy} onPick={(h) => void changeMapping(f.name, h)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="table-scroll" tabIndex={0} role="region" aria-label="Sample rows table">
            <table>
              <caption>First rows of your file</caption>
              <thead>
                <tr>
                  <th scope="col">Row</th>
                  {preview.headers.map((h) => (
                    <th scope="col" key={h}>
                      {h}
                    </th>
                  ))}
                  <th scope="col">Result</th>
                </tr>
              </thead>
              <tbody>
                {preview.sample.map((r) => (
                  <tr key={r.id}>
                    <th scope="row">{r.row_no}</th>
                    {preview.headers.map((h) => (
                      <td key={h}>{r.raw[h] ?? ''}</td>
                    ))}
                    <td>{r.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            <button onClick={() => void startReview()} disabled={busy}>
              Continue
            </button>{' '}
            <button className="secondary" onClick={() => void startOver()} disabled={busy}>
              Start over
            </button>
          </p>
        </section>
      )}

      {step === 'review' && preview && counts && (
        <section aria-label="Fix problem rows">
          <div role="status" aria-live="polite" data-testid="import-summary">
            {summarise(counts)}
          </div>
          {rows.length === 0 ? (
            <p data-testid="import-no-problems">No rows need fixing.</p>
          ) : (
            <ul className="import-rows" aria-label="Rows that need fixing">
              {rows.map((r) => (
                <FixRow key={r.id} row={r} entity={entity} mapping={mapping} onSave={saveRow} />
              ))}
            </ul>
          )}
          <p>
            <button onClick={() => void commit()} disabled={busy || readyCount(counts) === 0}>
              {busy ? 'Importing…' : `Commit ${readyCount(counts)} ${readyCount(counts) === 1 ? 'row' : 'rows'}`}
            </button>{' '}
            <button className="secondary" onClick={() => setReviewing(false)} disabled={busy}>
              Back to columns
            </button>{' '}
            <button className="secondary" onClick={() => void startOver()} disabled={busy}>
              Cancel import
            </button>
          </p>
        </section>
      )}

      {step === 'done' && result && preview && <Done projectId={projectId} entity={preview.entity} result={result} onAgain={() => void startOver()} />}
    </div>
  )
}

function MappingSelect({ field, headers, value, disabled, onPick }: { field: string; headers: string[]; value: string; disabled: boolean; onPick: (h: string) => void }) {
  const id = useId()
  return (
    <>
      <label htmlFor={id} className="sr-only">
        Column for {field}
      </label>
      <select id={id} value={value} disabled={disabled} onChange={(e) => onPick(e.target.value)}>
        <option value="">(do not import)</option>
        {headers.map((h) => (
          <option key={h} value={h}>
            {h}
          </option>
        ))}
      </select>
    </>
  )
}

function FixRow({ row, entity, mapping, onSave }: { row: ImportRow; entity: SpecEntity; mapping: Record<string, string>; onSave: (row: ImportRow, edits: Record<string, string>) => Promise<void> }) {
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const base = useId()
  const grouped = useMemo(() => groupErrors(row.errors), [row.errors])
  const fields = fixableFields(row, entity.fields)

  const save = async () => {
    setSaving(true)
    setProblem(null)
    try {
      await onSave(row, edits)
    } catch (err) {
      setProblem(msg(err, 'Could not save this row'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <li data-testid="import-row">
      <h3>Row {row.row_no}</h3>
      <dl>
        {Object.entries(row.raw).map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v === '' ? '(empty)' : v}</dd>
          </div>
        ))}
      </dl>
      <ul aria-label={`Problems in row ${row.row_no}`}>
        {grouped.map((g) => (
          <li key={g.field}>
            <strong>{g.field}</strong>: {g.messages.join('; ')}
          </li>
        ))}
      </ul>
      {fields.map((f) => (
        <p key={f}>
          <label htmlFor={`${base}-${f}`}>
            Fix {f} (row {row.row_no})
          </label>{' '}
          <input id={`${base}-${f}`} value={edits[f] ?? startValue(row, mapping, f)} onChange={(e) => setEdits((cur) => ({ ...cur, [f]: e.target.value }))} />
        </p>
      ))}
      {problem && <div role="alert">{problem}</div>}
      <button onClick={() => void save()} disabled={saving || fields.length === 0}>
        {saving ? 'Saving…' : `Save row ${row.row_no}`}
      </button>
    </li>
  )
}

function Done({ projectId, entity, result, onAgain }: { projectId: string; entity: string; result: ImportCommitResult; onAgain: () => void }) {
  const [records, setRecords] = useState<ImportRecord[] | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let cancelled = false
    api
      .listImportRecords(projectId, entity)
      .then((page) => {
        if (!cancelled) setRecords(page.items)
      })
      .catch(() => {
        if (!cancelled) setFailed(true)
      })
    return () => {
      cancelled = true
    }
  }, [projectId, entity])

  return (
    <section aria-label="Import finished">
      <div role="status" aria-live="polite" data-testid="import-result">
        <h2>Import finished</h2>
        <p>
          {result.created} created, {result.duplicate} already imported, {result.rejected} rejected.
        </p>
      </div>
      {failed && <p role="alert">The imported records could not be listed, but the import itself went through.</p>}
      {records && records.length === 0 && <p>No imported records to show.</p>}
      {records && records.length > 0 && (
        <ul aria-label="Imported records" data-testid="import-records">
          {records.map((r) => (
            <li key={r.id}>{Object.entries(r.data).map(([k, v]) => `${k}: ${String(v)}`).join(', ')}</li>
          ))}
        </ul>
      )}
      <p>
        <button onClick={onAgain}>Import another file</button>
      </p>
    </section>
  )
}
