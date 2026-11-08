import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { HistoryBody } from '../../api/types'
import { blankHistory, historyFromBody, historyToBody, looksSecret, type HistoryRow } from './formLogic'
import { useSection, type SectionConfig } from './useSection'
import { ConflictBanner, Field, IssueSummary, LoadFailed, SaveBar } from './ui'

const HISTORY: SectionConfig<HistoryRow, HistoryBody> = {
  key: 'history',
  load: async (id) => { const r = await api.getHistory(id); return { version: r.version, items: r.history } },
  save: async (id, items, v) => { const r = await api.putHistory(id, items, v); return { version: r.version, items: r.history } },
  fromBody: historyFromBody,
  toBody: historyToBody,
}

type Catalog = Record<string, { fields: string[]; stateField: string | null }>
type CatalogLoad = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; catalog: Catalog }

/** Why a field cannot be audited, or null when it can. Mirrors the backend rules (secret words, state field). */
export function whyDisabled(field: string, stateField: string | null): string | null {
  if (looksSecret(field)) return 'Looks like a secret: history is readable by roles and kept, so secrets are never recorded.'
  if (stateField === field) return 'This is the state field: its changes are already logged in the state history.'
  return null
}

async function loadCatalog(projectId: string): Promise<Catalog> {
  const entities = []
  for (let offset = 0; ; offset += 200) {
    const page = await api.listEntities(projectId, 200, offset)
    entities.push(...page.items)
    if (entities.length >= page.total || page.items.length === 0) break
  }
  const machines = await api.getStateMachines(projectId)
  const out: Catalog = {}
  await Promise.all(
    entities.map(async (e) => {
      const fields = await api.listFields(e.id, 200, 0)
      out[e.name] = {
        fields: fields.items.map((f) => f.name),
        stateField: machines.state_machines.find((m) => m.entity === e.name)?.field ?? null,
      }
    }),
  )
  return out
}

export function HistoryPage({ projectId }: { projectId: string }) {
  const { state: st, change, save, reload } = useSection(projectId, HISTORY)
  const [cat, setCat] = useState<CatalogLoad>({ status: 'loading' })
  const [pick, setPick] = useState('')

  const loadCat = useCallback(() => {
    setCat({ status: 'loading' })
    loadCatalog(projectId).then(
      (catalog) => setCat({ status: 'ready', catalog }),
      (err: unknown) => setCat({ status: 'error', message: err instanceof Error ? err.message : 'Could not load the entities' }),
    )
  }, [projectId])
  useEffect(loadCat, [loadCat])

  const retry = () => { reload(); loadCat() }

  const header = (
    <div className="page-header">
      <div>
        <h1>Change history</h1>
        <p>Records who changed which fields of a record, and what the old and new values were, for as long as you choose to keep them.</p>
      </div>
    </div>
  )
  if (st.status === 'loading' || cat.status === 'loading') return <>{header}<p className="empty-state">Loading change history…</p></>
  if (st.status === 'error') return <>{header}<LoadFailed what="the change history settings" message={st.loadError} onRetry={retry} /></>
  if (cat.status === 'error') return <>{header}<LoadFailed what="the entities" message={cat.message} onRetry={retry} /></>

  const catalog = cat.catalog
  const free = Object.keys(catalog).filter((n) => !st.rows.some((r) => r.entity === n))
  const msgs = (i: number, f: string) => [
    ...(st.clientErrs[`${i}.${f}`] ? [st.clientErrs[`${i}.${f}`]] : []),
    ...(st.issues.rows[i]?.fields[f] ?? []),
  ]
  const patch = (i: number, p: Partial<HistoryRow>, field: string) =>
    change(st.rows.map((r, n) => (n === i ? { ...r, ...p } : r)), [i, field])

  return (
    <>
      {header}
      {st.conflict && <ConflictBanner onReload={retry} />}
      <IssueSummary issues={st.issues} />
      {st.rows.length === 0 && (
        <div className="card empty-hero" data-testid="history-empty">
          <h2>No change history yet</h2>
          <p>Pick an entity below and tick the fields whose changes you want to keep, for example the status and the assignee of a ticket.</p>
        </div>
      )}
      {st.rows.map((r, i) => {
        const known = catalog[r.entity]
        const id = `hy-${r.k}`
        // fields named in the config that the entity no longer has stay listed so the backend message can point at them
        const fieldNames = [...(known?.fields ?? []), ...r.fields.filter((f) => !(known?.fields ?? []).includes(f))]
        return (
          <fieldset key={r.k} className="card bh-row" data-testid="history-row">
            <legend>{r.entity}</legend>
            {(st.issues.rows[i]?.row ?? []).length > 0 && <div role="alert" data-variant="danger" className="bh-alert">{st.issues.rows[i].row.join(' ')}</div>}
            {msgs(i, 'entity').length > 0 && <div role="alert" data-variant="danger" className="bh-alert">{msgs(i, 'entity').join(' ')}</div>}
            <div className="bh-checks" role="group" aria-label={`Fields of ${r.entity} to record`}>
              {fieldNames.map((f) => {
                const why = whyDisabled(f, known?.stateField ?? null)
                const k = r.fields.indexOf(f)
                const fm = k >= 0 ? msgs(i, `fields[${k}]`) : []
                const fid = `${id}-f-${f}`
                return (
                  <div key={f} className="bh-check" data-invalid={fm.length > 0 || undefined}>
                    <input
                      id={fid} type="checkbox" checked={k >= 0} disabled={!!why && k < 0}
                      aria-describedby={why ? `${fid}-why` : fm.length ? `${fid}-err` : undefined}
                      aria-invalid={fm.length > 0 || undefined}
                      onChange={(e) => patch(i, { fields: e.target.checked ? [...r.fields, f] : r.fields.filter((x) => x !== f) }, 'fields')}
                    />
                    <label htmlFor={fid}>{f}</label>
                    {why && <small id={`${fid}-why`} className="muted">{why}</small>}
                    {fm.length > 0 && <small id={`${fid}-err`} className="bh-error" data-testid="field-error">{fm.join(' ')}</small>}
                  </div>
                )
              })}
            </div>
            {msgs(i, 'fields').length > 0 && <div role="alert" data-variant="danger" className="bh-alert">{msgs(i, 'fields').join(' ')}</div>}
            <div className="bh-grid">
              <Field id={`${id}-days`} label="Keep for (days)" hint="1 to 3650" messages={msgs(i, 'retention_days')}>
                {(p) => <input {...p} inputMode="numeric" value={r.retention_days} onChange={(e) => patch(i, { retention_days: e.target.value }, 'retention_days')} />}
              </Field>
              <Field id={`${id}-roles`} label="Who can read the history" hint="Role names, separated by commas. Empty: nobody (no route is generated)" messages={msgs(i, 'view_roles')}>
                {(p) => <input {...p} value={r.view_roles} onChange={(e) => patch(i, { view_roles: e.target.value }, 'view_roles')} />}
              </Field>
            </div>
            <button className="outline small" aria-label={`Remove history of ${r.entity}`} onClick={() => change(st.rows.filter((_, n) => n !== i))}>Remove</button>
          </fieldset>
        )
      })}
      <div className="bh-actions">
        {free.length > 0 ? (
          <>
            <label htmlFor="hy-pick" className="sr-only">Entity to record</label>
            <select id="hy-pick" value={pick || free[0]} onChange={(e) => setPick(e.target.value)}>
              {free.map((n) => <option key={n}>{n}</option>)}
            </select>
            <button className="outline" onClick={() => { change([...st.rows, blankHistory(pick || free[0])]); setPick('') }}>Record history for this entity</button>
          </>
        ) : (
          <small className="muted">{Object.keys(catalog).length === 0 ? 'Add an entity in the data model first.' : 'Every entity already has a history config.'}</small>
        )}
      </div>
      <SaveBar dirty={st.dirty} saving={st.saving} onSave={save} onDiscard={reload} note={st.savedNote} error={st.saveError} />
    </>
  )
}
