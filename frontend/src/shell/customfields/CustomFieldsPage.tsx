import { useCallback, useEffect, useId, useState } from 'react'
import { api } from '../../api/client'
import type { CustomFieldDef, PromoteCheck } from '../../api/types'
import { entitiesOf } from '../import/importLogic'

const TYPES = ['string', 'int', 'float', 'bool', 'date', 'datetime']
const msg = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback)

type Load = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; entities: string[] }

export function CustomFieldsPage({ projectId }: { projectId: string }) {
  const [load, setLoad] = useState<Load>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let cancelled = false
    setLoad({ status: 'loading' })
    api
      .getSpecJson(projectId)
      .then((spec) => {
        if (!cancelled) setLoad({ status: 'ready', entities: entitiesOf(spec).map((e) => e.name) })
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
          <h1>Custom fields</h1>
          <p>Add extra fields to an entity without a schema change. When a field proves its worth, check it and promote it to a real column.</p>
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
      {load.status === 'ready' && load.entities.length === 0 && <p className="empty-state" data-testid="cf-empty">No entities yet. Add one in the data model first.</p>}
      {load.status === 'ready' && load.entities.length > 0 && <Editor projectId={projectId} entities={load.entities} />}
    </>
  )
}

function Editor({ projectId, entities }: { projectId: string; entities: string[] }) {
  const [entity, setEntity] = useState(entities[0])
  const [items, setItems] = useState<CustomFieldDef[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [name, setName] = useState('')
  const [type, setType] = useState('string')
  const [required, setRequired] = useState(false)
  const [check, setCheck] = useState<{ name: string; result: PromoteCheck } | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const eid = useId()
  const nid = useId()
  const tid = useId()
  const rid = useId()

  const reload = useCallback(async () => {
    try {
      setItems((await api.listCustomFields(projectId, entity)).items)
    } catch (err) {
      setError(msg(err, 'Could not list the custom fields'))
    }
  }, [projectId, entity])

  useEffect(() => {
    setItems(null)
    setCheck(null)
    setNotice(null)
    setError(null)
    void reload()
  }, [reload])

  const run = async (fn: () => Promise<void>, fallback: string) => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await fn()
    } catch (err) {
      setError(msg(err, fallback))
    } finally {
      setBusy(false)
    }
  }

  const define = () =>
    run(async () => {
      await api.defineCustomField(projectId, entity, { name: name.trim(), type, required })
      setName('')
      setRequired(false)
      await reload()
    }, 'Could not add the field')

  const remove = (n: string) =>
    run(async () => {
      await api.removeCustomField(projectId, entity, n)
      setCheck(null)
      await reload()
    }, 'Could not remove the field')

  const runCheck = (n: string) =>
    run(async () => setCheck({ name: n, result: await api.checkPromoteCustomField(projectId, entity, n) }), 'Could not check the field')

  const promote = (n: string) =>
    run(async () => {
      await api.promoteCustomField(projectId, entity, n)
      setCheck(null)
      setNotice(`${n} is now a real column. The change is in the history and can be reviewed there.`)
      await reload()
    }, 'Could not promote the field')

  return (
    <div className="card">
      <p>
        <label htmlFor={eid}>Entity</label>{' '}
        <select id={eid} value={entity} onChange={(e) => setEntity(e.target.value)}>
          {entities.map((e) => (
            <option key={e} value={e}>
              {e}
            </option>
          ))}
        </select>
      </p>
      {error && (
        <div role="alert" data-testid="cf-error">
          {error}
        </div>
      )}
      {notice && (
        <div role="status" data-testid="cf-notice">
          {notice}
        </div>
      )}
      {items === null ? (
        <p className="empty-state">Loading…</p>
      ) : items.length === 0 ? (
        <p data-testid="cf-none">No custom fields on {entity} yet.</p>
      ) : (
        <div className="table-scroll" tabIndex={0} role="region" aria-label="Custom fields table">
          <table>
            <caption>Custom fields on {entity}</caption>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Type</th>
                <th scope="col">Required</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((f) => (
                <tr key={f.name} data-testid="cf-row">
                  <th scope="row">{f.name}</th>
                  <td>{f.type}</td>
                  <td>{f.required ? 'yes' : 'no'}</td>
                  <td>
                    <button className="secondary" disabled={busy} onClick={() => void runCheck(f.name)}>
                      Check {f.name} for promotion
                    </button>{' '}
                    <button className="secondary" disabled={busy} onClick={() => void remove(f.name)}>
                      Remove {f.name}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {check && (
        <section aria-label="Promotion check" data-testid="cf-check">
          <h2>Promote {check.name}</h2>
          {check.result.ok ? <p>Ready: the field can become a real column.</p> : <p>Not ready: fix these problems first.</p>}
          {check.result.problems.length > 0 && (
            <ul aria-label="Problems">
              {check.result.problems.map((p, i) => (
                <li key={i}>{p.message}</li>
              ))}
            </ul>
          )}
          {check.result.plan_sql.length > 0 && (
            <pre aria-label="What will run">{check.result.plan_sql.join('\n')}</pre>
          )}
          <button disabled={busy || !check.result.ok} onClick={() => void promote(check.name)}>
            Promote {check.name} to a column
          </button>
        </section>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          void define()
        }}
      >
        <h2>Add a field</h2>
        <p>
          <label htmlFor={nid}>Field name</label> <input id={nid} value={name} onChange={(e) => setName(e.target.value)} />
        </p>
        <p>
          <label htmlFor={tid}>Type</label>{' '}
          <select id={tid} value={type} onChange={(e) => setType(e.target.value)}>
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </p>
        <p>
          <input id={rid} type="checkbox" checked={required} onChange={(e) => setRequired(e.target.checked)} /> <label htmlFor={rid}>Required</label>
        </p>
        <button type="submit" disabled={busy || name.trim() === ''}>
          Add field
        </button>
      </form>
    </div>
  )
}
