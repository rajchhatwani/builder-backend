import { useCallback, useEffect, useId, useRef, useState } from 'react'
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
  const [confirm, setConfirm] = useState<{ kind: 'remove' | 'promote'; name: string } | null>(null)
  const [ackUnproven, setAckUnproven] = useState(false)
  const triggerRef = useRef<HTMLElement | null>(null)
  const cancelRef = useRef<HTMLButtonElement | null>(null)
  const reqId = useRef(0)
  const eid = useId()
  const nid = useId()
  const tid = useId()
  const rid = useId()
  const ackId = useId()

  const reload = useCallback(async () => {
    const mine = ++reqId.current
    try {
      const res = await api.listCustomFields(projectId, entity)
      if (mine === reqId.current) setItems(res.items)
    } catch (err) {
      if (mine === reqId.current) setError(msg(err, 'Could not list the custom fields'))
    }
  }, [projectId, entity])

  useEffect(() => {
    setItems(null)
    setCheck(null)
    setNotice(null)
    setError(null)
    setConfirm(null)
    setAckUnproven(false)
    void reload()
    return () => {
      reqId.current++
    }
  }, [reload])

  useEffect(() => {
    if (confirm) cancelRef.current?.focus()
  }, [confirm])

  const ask = (kind: 'remove' | 'promote', n: string, e: { currentTarget: HTMLElement }) => {
    triggerRef.current = e.currentTarget
    setConfirm({ kind, name: n })
  }
  const closeConfirm = () => {
    setConfirm(null)
    const t = triggerRef.current
    // return focus to the control that opened the dialog (it may have been re-rendered away)
    setTimeout(() => (t && t.isConnected ? t : document.querySelector<HTMLElement>('[data-testid=cf-entity]'))?.focus(), 0)
  }

  const warnings = Array.isArray(check?.result.warnings) ? (check!.result.warnings as string[]) : []
  const proven = check?.result.proven === true && warnings.length === 0

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
      setConfirm(null)
      await reload()
    }, 'Could not remove the field')

  const runCheck = (n: string) =>
    run(async () => {
      const result = await api.checkPromoteCustomField(projectId, entity, n)
      setAckUnproven(false)
      setCheck({ name: n, result })
    }, 'Could not check the field')

  const promote = (n: string) =>
    run(async () => {
      await api.promoteCustomField(projectId, entity, n)
      setCheck(null)
      setConfirm(null)
      setNotice(`${n} is now a real column. The change is in the history and can be reviewed there.`)
      await reload()
    }, 'Could not promote the field')

  return (
    <div className="card">
      <p>
        <label htmlFor={eid}>Entity</label>{' '}
        <select id={eid} data-testid="cf-entity" value={entity} onChange={(e) => setEntity(e.target.value)}>
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
                    <button className="secondary" disabled={busy} onClick={(e) => ask('remove', f.name, e)}>
                      Remove {f.name}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {confirm && (
        <div
          role="alertdialog"
          aria-modal="true"
          aria-labelledby={`${eid}-ct`}
          data-testid="cf-confirm"
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.stopPropagation()
              closeConfirm()
            }
          }}
        >
          <p id={`${eid}-ct`}>
            {confirm.kind === 'remove'
              ? `Remove the custom field ${confirm.name}? Values already stored on rows are left in place but the field is no longer defined.`
              : `Promote ${confirm.name} to a real column? This is a schema change that runs a migration.`}
          </p>
          <button ref={cancelRef} className="secondary" onClick={closeConfirm} disabled={busy}>
            Cancel
          </button>{' '}
          <button
            disabled={busy}
            onClick={() => {
              const c = confirm
              void (c.kind === 'remove' ? remove(c.name) : promote(c.name)).then(closeConfirm)
            }}
          >
            {confirm.kind === 'remove' ? `Yes, remove ${confirm.name}` : `Yes, promote ${confirm.name}`}
          </button>
        </div>
      )}
      {check && (
        <section aria-label="Promotion check" data-testid="cf-check">
          <h2>Promote {check.name}</h2>
          {!check.result.ok ? (
            <p>Not ready: fix these problems first.</p>
          ) : proven ? (
            <p>Ready: the field can become a real column.</p>
          ) : (
            <p data-testid="cf-not-proven">Not proven: the check could not show that every existing row will convert. Review the warnings below.</p>
          )}
          {warnings.length > 0 && (
            <ul aria-label="Warnings">
              {warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}
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
          {check.result.ok && !proven && (
            <p>
              <input id={ackId} type="checkbox" checked={ackUnproven} onChange={(e) => setAckUnproven(e.target.checked)} />{' '}
              <label htmlFor={ackId}>I understand this is not proven and the change may fail on existing data</label>
            </p>
          )}
          <button disabled={busy || !check.result.ok || (!proven && !ackUnproven)} onClick={(e) => ask('promote', check.name, e)}>
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
