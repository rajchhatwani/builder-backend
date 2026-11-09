import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { api } from '../../api/client'
import type { AccessDiff, AccessDiffRequest, AccessLayer, AccessMatrix, FieldAccessRule, PermissionRule } from '../../api/types'
import { link } from '../../components/Sidebar'
import {
  LAYERS, editableRoles, fieldAccessOf, fieldNames, fieldRolesOf, groupTable, permissionsOf, rolesOfOperation,
  setFieldRoles, summariseDiff, toggleRole, withEdits,
} from './accessLogic'

type Load =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; matrix: AccessMatrix; spec: Record<string, unknown> }

type Review = { status: 'checking' } | { status: 'error'; message: string } | { status: 'ready'; diff: AccessDiff }

const msg = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback)

export function AccessPage({ projectId }: { projectId: string }) {
  const [load, setLoad] = useState<Load>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoad({ status: 'loading' })
    Promise.all([api.getAccessMatrix(projectId), api.getSpecJson(projectId)])
      .then(([matrix, spec]) => {
        if (!cancelled) setLoad({ status: 'ready', matrix, spec })
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoad({ status: 'error', message: msg(err, 'Could not load the access matrix') })
      })
    return () => {
      cancelled = true
    }
  }, [projectId, attempt])

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Access</h1>
          <p>See which role can do what, per entity: whole operations (object), single fields, and which rows. Edit a rule and review exactly who gains or loses access before anything is saved.</p>
        </div>
      </div>
      {load.status === 'loading' && <p className="empty-state">Loading the access matrix…</p>}
      {load.status === 'error' && (
        <div className="card empty-hero" role="alert">
          <h2>We could not load the access matrix</h2>
          <p>{load.message}</p>
          <button onClick={() => setAttempt((n) => n + 1)}>Try again</button>
        </div>
      )}
      {load.status === 'ready' && load.matrix.entities.length === 0 && (
        <div className="card empty-hero" data-testid="access-empty">
          <h2>No entities yet</h2>
          <p>Access is decided per entity. Add one first, then come back to see who can use it.</p>
          <a className="button" href={link(`/p/${projectId}/model`)}>
            Open the data model
          </a>
        </div>
      )}
      {load.status === 'ready' && load.matrix.entities.length > 0 && (
        <Matrix projectId={projectId} matrix={load.matrix} spec={load.spec} onApplied={() => setAttempt((n) => n + 1)} />
      )}
    </>
  )
}

function Matrix({ projectId, matrix, spec, onApplied }: { projectId: string; matrix: AccessMatrix; spec: Record<string, unknown>; onApplied: () => void }) {
  const [layer, setLayer] = useState<AccessLayer>('object')
  const [entity, setEntity] = useState(matrix.entities[0])
  const [draft, setDraft] = useState<AccessDiffRequest | null>(null)
  const [review, setReview] = useState<Review | null>(null)
  const [applying, setApplying] = useState(false)
  const [applyError, setApplyError] = useState<string | null>(null)
  const entityId = useId()
  const seq = useRef(0)

  const savedPerms = useMemo(() => permissionsOf(spec), [spec])
  const savedFields = useMemo(() => fieldAccessOf(spec), [spec])
  const perms = draft?.permissions ?? savedPerms
  const fields = draft?.field_access ?? savedFields

  useEffect(() => {
    if (!draft) {
      setReview(null)
      return
    }
    const mine = ++seq.current
    setReview({ status: 'checking' })
    api
      .diffAccess(projectId, draft)
      .then((diff) => {
        if (mine === seq.current) setReview({ status: 'ready', diff })
      })
      .catch((err: unknown) => {
        if (mine === seq.current) setReview({ status: 'error', message: msg(err, 'Could not work out what would change') })
      })
  }, [draft, projectId])

  const edit = (next: { permissions?: PermissionRule[]; field_access?: FieldAccessRule[] }) => {
    setApplyError(null)
    setDraft({ permissions: next.permissions ?? draft?.permissions ?? null, field_access: next.field_access ?? draft?.field_access ?? null })
  }

  const apply = useCallback(async () => {
    if (!draft || review?.status !== 'ready') return
    setApplying(true)
    setApplyError(null)
    try {
      await api.applySpecOp(projectId, 'replace_spec', { spec: withEdits(spec, draft) }, review.diff.weakens)
      setDraft(null)
      onApplied()
    } catch (err) {
      setApplyError(msg(err, 'Could not apply the change'))
    } finally {
      setApplying(false)
    }
  }, [draft, review, projectId, spec, onApplied])

  const table = groupTable(matrix, layer, entity)
  const label = LAYERS.find((l) => l.id === layer)!.label

  return (
    <>
      <div className="access-controls" style={{ display: 'flex', gap: 'var(--space-4)', flexWrap: 'wrap', alignItems: 'flex-end', marginBlockEnd: 'var(--space-3)' }}>
        <div role="group" aria-label="Layer" className="access-layers">
          {LAYERS.map((l) => (
            <button key={l.id} className={l.id === layer ? '' : 'ghost'} aria-pressed={l.id === layer} onClick={() => setLayer(l.id)}>
              {l.label}
            </button>
          ))}
        </div>
        <div className="access-entity">
          <label htmlFor={entityId}>Entity</label>{' '}
          <select id={entityId} value={entity} onChange={(e) => setEntity(e.target.value)}>
            {matrix.entities.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </div>
      </div>

      {table.targets.length === 0 ? (
        <p className="empty-state" data-testid="access-layer-empty">No {label.toLowerCase()} rules to show for {entity}.</p>
      ) : (
        <div style={{ overflowX: 'auto' }} tabIndex={0} role="region" aria-label={`${label} access table`}>
          <table data-testid="access-table">
            <caption>{label} access for {entity}: what each role gets, per {layer === 'field' ? 'field and kind of access' : 'operation'}</caption>
            <thead>
              <tr>
                <th scope="col">Role</th>
                {table.targets.map((t) => (
                  <th key={t} scope="col">{t}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.roles.map((role) => (
                <tr key={role}>
                  <th scope="row">{role}</th>
                  {table.targets.map((t) => (
                    <td key={t}>{table.values[role]?.[t] ?? '—'}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {layer === 'object' && (
        <ObjectEditor entity={entity} operations={table.targets} roles={editableRoles(matrix)} rules={perms} onChange={(rules) => edit({ permissions: rules })} />
      )}
      {layer === 'field' && (
        <FieldEditor entity={entity} fieldList={fieldNames(matrix, entity)} roles={editableRoles(matrix)} rules={fields} onChange={(rules) => edit({ field_access: rules })} />
      )}

      {draft && (
        <ReviewPanel review={review} applying={applying} applyError={applyError} onApply={apply} onDiscard={() => { setDraft(null); setApplyError(null) }} />
      )}
    </>
  )
}

function ObjectEditor({ entity, operations, roles, rules, onChange }: { entity: string; operations: string[]; roles: string[]; rules: PermissionRule[]; onChange: (r: PermissionRule[]) => void }) {
  const [op, setOp] = useState('')
  const id = useId()
  const current = operations.includes(op) ? op : operations[0]
  if (!current) return null
  const allowed = rolesOfOperation(rules, entity, current)
  return (
    <section className="card" aria-labelledby={`${id}-h`} style={{ marginBlock: 'var(--space-4)' }}>
      <h2 id={`${id}-h`}>Edit who may use an operation</h2>
      <p className="muted">Roles ticked here are listed on the rule directly. Roles that inherit another role keep that access too.</p>
      <label htmlFor={`${id}-op`}>Operation</label>{' '}
      <select id={`${id}-op`} value={current} onChange={(e) => setOp(e.target.value)}>
        {operations.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
      <fieldset>
        <legend>Roles allowed to {current}</legend>
        {roles.map((r) => (
          <label key={r} style={{ marginInlineEnd: 'var(--space-4)' }}>
            <input type="checkbox" checked={allowed.includes(r)} onChange={(e) => onChange(toggleRole(rules, entity, current, r, e.target.checked))} /> {r}
          </label>
        ))}
      </fieldset>
    </section>
  )
}

function FieldEditor({ entity, fieldList, roles, rules, onChange }: { entity: string; fieldList: string[]; roles: string[]; rules: FieldAccessRule[]; onChange: (r: FieldAccessRule[]) => void }) {
  const [field, setField] = useState('')
  const id = useId()
  const current = fieldList.includes(field) ? field : fieldList[0]
  if (!current) return null
  const now = fieldRolesOf(rules, entity, current)
  const set = (kind: 'read_roles' | 'write_roles', value: string[] | null) => onChange(setFieldRoles(rules, entity, current, { ...now, [kind]: value }))
  const group = (kind: 'read_roles' | 'write_roles', title: string) => {
    const list = now[kind]
    return (
      <fieldset key={kind}>
        <legend>{title}</legend>
        <label style={{ marginInlineEnd: 'var(--space-4)' }}>
          <input type="checkbox" checked={list === null} onChange={(e) => set(kind, e.target.checked ? null : [...roles])} /> No field rule (follows the operation)
        </label>
        {roles.map((r) => (
          <label key={r} style={{ marginInlineEnd: 'var(--space-4)' }}>
            <input
              type="checkbox"
              disabled={list === null}
              checked={list?.includes(r) ?? false}
              aria-label={`${r} may ${kind === 'read_roles' ? 'read' : 'write'} ${current}`}
              onChange={(e) => set(kind, e.target.checked ? [...(list ?? []), r] : (list ?? []).filter((x) => x !== r))}
            />{' '}
            {r}
          </label>
        ))}
      </fieldset>
    )
  }
  return (
    <section className="card" aria-labelledby={`${id}-h`} style={{ marginBlock: 'var(--space-4)' }}>
      <h2 id={`${id}-h`}>Edit who may read or write a field</h2>
      <p className="muted">A field rule can only narrow what the operation already allows.</p>
      <label htmlFor={`${id}-f`}>Field</label>{' '}
      <select id={`${id}-f`} value={current} onChange={(e) => setField(e.target.value)}>
        {fieldList.map((f) => (
          <option key={f} value={f}>{f}</option>
        ))}
      </select>
      {group('read_roles', `Roles that may read ${current}`)}
      {group('write_roles', `Roles that may write ${current}`)}
    </section>
  )
}

function ReviewPanel({ review, applying, applyError, onApply, onDiscard }: { review: Review | null; applying: boolean; applyError: string | null; onApply: () => void; onDiscard: () => void }) {
  const id = useId()
  const summary = review?.status === 'ready' ? summariseDiff(review.diff) : null
  return (
    <section className="card" aria-labelledby={`${id}-h`} data-testid="access-review" style={{ marginBlock: 'var(--space-4)' }}>
      <h2 id={`${id}-h`}>Review changes</h2>
      <div aria-live="polite">
        {(!review || review.status === 'checking') && <p>Working out what would change…</p>}
        {review?.status === 'error' && <p role="alert">{review.message}</p>}
        {summary && summary.total === 0 && <p data-testid="access-no-change">No one gains or loses access with this edit.</p>}
        {summary && summary.weakens && (
          <p role="alert" data-testid="access-weakens">
            Warning: this gives at least one role more access than it has today. You must confirm that to apply it.
          </p>
        )}
        {summary && summary.lines.length > 0 && (
          <ul data-testid="access-diff-lines">
            {summary.lines.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        )}
        {summary && summary.total > 0 && summary.lines.length === 0 && <p>{summary.total} cell(s) change without any role gaining or losing access.</p>}
      </div>
      {applyError && <p role="alert">{applyError}</p>}
      <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
        <button onClick={onApply} disabled={!summary || summary.total === 0 || applying}>
          {summary?.weakens ? 'Apply and confirm more access' : 'Apply change'}
        </button>
        <button className="ghost" onClick={onDiscard} disabled={applying}>Discard</button>
      </div>
    </section>
  )
}
