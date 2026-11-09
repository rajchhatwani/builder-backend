import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { api } from '../../api/client'
import type { MetricRead, MetricValue, ReportRead, ReportRunRead, ReportValue } from '../../api/types'
import {
  AGGS, CRON_PRESETS, TIMEZONES, cronLabel, definitionToForm, emptyMetricForm, emptyReportForm, entitiesOf, errorMessage, fieldsForAgg,
  formToDefinition, formToReport, formatGroups, formatValue, isNumericType, opsFor, presetOf, reportToForm, scalarFields, slotOf, slotText,
  toggleKey, unitOf, validateMetricForm, validateReportForm,
} from './metricsLogic'
import type { MetricForm, ReportForm, SpecEntity } from './metricsLogic'

type Load =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; entities: SpecEntity[]; metrics: MetricRead[]; reports: ReportRead[] }

const TABS = [{ id: 'metrics', label: 'Metrics' }, { id: 'reports', label: 'Reports' }] as const
type TabId = (typeof TABS)[number]['id']

export function MetricsPage({ projectId }: { projectId: string }) {
  const [load, setLoad] = useState<Load>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  const [tab, setTab] = useState<TabId>('metrics')
  const refs = useRef<Record<string, HTMLButtonElement | null>>({})

  const reload = useCallback(async () => {
    const [spec, metrics, reports] = await Promise.all([api.getSpecJson(projectId), api.listMetrics(projectId), api.listReports(projectId)])
    return { entities: entitiesOf(spec), metrics: metrics.items, reports: reports.items }
  }, [projectId])

  useEffect(() => {
    let cancelled = false
    setLoad({ status: 'loading' })
    reload()
      .then((r) => { if (!cancelled) setLoad({ status: 'ready', ...r }) })
      .catch((err: unknown) => { if (!cancelled) setLoad({ status: 'error', message: errorMessage(err, 'Could not load metrics') }) })
    return () => { cancelled = true }
  }, [reload, attempt])

  const refresh = async () => {
    try {
      setLoad({ status: 'ready', ...(await reload()) })
    } catch (err) {
      setLoad({ status: 'error', message: errorMessage(err, 'Could not load metrics') })
    }
  }

  const onKey = (e: KeyboardEvent) => {
    const i = TABS.findIndex((t) => t.id === tab)
    const n = e.key === 'ArrowRight' ? (i + 1) % TABS.length : e.key === 'ArrowLeft' ? (i + TABS.length - 1) % TABS.length : -1
    if (n < 0) return
    e.preventDefault()
    setTab(TABS[n].id)
    refs.current[TABS[n].id]?.focus()
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Metrics &amp; reports</h1>
          <p>Define a number once, such as open invoices or total paid, and use it everywhere. Reports collect metrics and run on a schedule.</p>
        </div>
      </div>
      {load.status === 'loading' && <p className="empty-state">Loading…</p>}
      {load.status === 'error' && (
        <div className="card empty-hero" role="alert" data-testid="metrics-error">
          <h2>We could not load this page</h2>
          <p>{load.message}</p>
          <button onClick={() => setAttempt((n) => n + 1)}>Try again</button>
        </div>
      )}
      {load.status === 'ready' && (
        <>
          <div role="tablist" aria-label="Metrics and reports" className="stage-tablist" onKeyDown={onKey}>
            {TABS.map((t) => (
              <button key={t.id} ref={(el) => { refs.current[t.id] = el }} type="button" role="tab" id={`metrics-tab-${t.id}`} aria-selected={tab === t.id}
                aria-controls={`metrics-panel-${t.id}`} tabIndex={tab === t.id ? 0 : -1} className={`stage-tab${tab === t.id ? ' is-active' : ''}`} onClick={() => setTab(t.id)}>
                {t.label}
              </button>
            ))}
          </div>
          <div role="tabpanel" id={`metrics-panel-${tab}`} aria-labelledby={`metrics-tab-${tab}`}>
            {tab === 'metrics' && <MetricsTab projectId={projectId} entities={load.entities} metrics={load.metrics} onChanged={refresh} />}
            {tab === 'reports' && <ReportsTab projectId={projectId} metrics={load.metrics} reports={load.reports} onChanged={refresh} />}
          </div>
        </>
      )}
    </>
  )
}

// -- metrics -----------------------------------------------------------------------------------

function MetricValueView({ projectId, metric }: { projectId: string; metric: MetricRead }) {
  const [state, setState] = useState<{ status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; value: MetricValue }>({ status: 'loading' })
  useEffect(() => {
    let cancelled = false
    setState({ status: 'loading' })
    api.getMetricValue(projectId, metric.key)
      .then((value) => { if (!cancelled) setState({ status: 'ready', value }) })
      .catch((err: unknown) => { if (!cancelled) setState({ status: 'error', message: errorMessage(err, 'Could not compute this value') }) })
    return () => { cancelled = true }
  }, [projectId, metric.key, metric.version])
  const unit = metric.definition.unit
  if (state.status === 'loading') return <span className="muted">Computing…</span>
  if (state.status === 'error') return <span role="alert" className="error-text small-text" data-testid={`metric-value-error-${metric.key}`}>{state.message}</span>
  const groups = formatGroups(state.value.groups, unit)
  return (
    <span>
      <strong data-testid={`metric-value-${metric.key}`}>{formatValue(state.value.value, unit)}</strong>
      {groups.length > 0 && (
        <ul className="small-text" aria-label={`${metric.definition.label} by ${metric.definition.group_by ?? 'group'}`}>
          {groups.map((g) => <li key={g.label}>{g.label}: {g.value}</li>)}
        </ul>
      )}
    </span>
  )
}

function describeMetric(m: MetricRead): string {
  const d = m.definition
  const agg = AGGS.find((a) => a.id === d.agg)?.label ?? d.agg
  const what = d.field ? `${agg.toLowerCase()} of ${d.field}` : agg.toLowerCase()
  const f = d.filter?.length ? `, ${d.filter.length} filter${d.filter.length === 1 ? '' : 's'}` : ''
  const g = d.group_by ? `, by ${d.group_by}` : ''
  return `${d.entity}: ${what}${f}${g}`
}

function MetricsTab({ projectId, entities, metrics, onChanged }: { projectId: string; entities: SpecEntity[]; metrics: MetricRead[]; onChanged: () => Promise<void> }) {
  const [editing, setEditing] = useState<{ key: string | null; form: MetricForm } | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const remove = async (key: string) => {
    setError(null)
    setNotice(null)
    try {
      await api.deleteMetric(projectId, key)
      setConfirmDelete(null)
      setNotice(`Deleted ${key}.`)
      await onChanged()
    } catch (err) {
      setConfirmDelete(null)
      setError(errorMessage(err, 'Could not delete the metric'))
    }
  }

  if (entities.length === 0) {
    return <div className="card empty-hero" data-testid="metrics-no-entities"><h2>Add an entity first</h2><p>Metrics measure the records of an entity, and this project has none yet.</p></div>
  }
  return (
    <>
      <div className="hstack">
        <h2 className="grow">Metrics</h2>
        {!editing && <button type="button" onClick={() => { setNotice(null); setError(null); setEditing({ key: null, form: emptyMetricForm(entities[0].name) }) }}>New metric</button>}
      </div>
      {notice && <p role="status" className="small-text">{notice}</p>}
      {error && <p role="alert" className="error-text" data-testid="metrics-action-error">{error}</p>}
      {editing && (
        <MetricFormView projectId={projectId} entities={entities} takenKeys={metrics.map((m) => m.key)} editingKey={editing.key} initial={editing.form}
          onCancel={() => setEditing(null)} onSaved={async () => { setEditing(null); await onChanged() }} />
      )}
      {metrics.length === 0 && !editing && (
        <div className="card empty-hero" data-testid="metrics-empty"><h2>No metrics yet</h2><p>Create the first one, for example the number of open invoices.</p></div>
      )}
      {metrics.length > 0 && (
        <ul className="ai-list" aria-label="Metrics">
          {metrics.map((m) => (
            <li key={m.key} className="card" data-testid="metric-row">
              <div className="hstack">
                <div className="grow">
                  <h3>{m.definition.label} <code className="small-text">{m.key}</code></h3>
                  <p className="small-text">{describeMetric(m)}</p>
                </div>
                <MetricValueView projectId={projectId} metric={m} />
              </div>
              <div className="hstack">
                <button type="button" className="btn btn-sm" aria-label={`Edit ${m.definition.label}`} onClick={() => { setNotice(null); setError(null); setEditing({ key: m.key, form: definitionToForm(m.definition) }) }}>Edit</button>
                {confirmDelete === m.key ? (
                  <>
                    <button type="button" className="btn btn-sm" onClick={() => void remove(m.key)}>Confirm delete {m.definition.label}</button>
                    <button type="button" className="btn btn-sm" onClick={() => setConfirmDelete(null)}>Keep it</button>
                  </>
                ) : (
                  <button type="button" className="btn btn-sm" aria-label={`Delete ${m.definition.label}`} onClick={() => setConfirmDelete(m.key)}>Delete</button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

function MetricFormView({ projectId, entities, takenKeys, editingKey, initial, onCancel, onSaved }: {
  projectId: string; entities: SpecEntity[]; takenKeys: string[]; editingKey: string | null; initial: MetricForm; onCancel: () => void; onSaved: () => Promise<void>
}) {
  const [form, setForm] = useState<MetricForm>(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showHints, setShowHints] = useState(false)
  const entity = entities.find((e) => e.name === form.entity)
  const problems = validateMetricForm(form, entities, editingKey !== null, takenKeys)
  const hint = (field: string) => (showHints ? problems.filter((p) => p.field === field).map((p) => p.message).join(' ') : '')
  const set = (patch: Partial<MetricForm>) => setForm((f) => ({ ...f, ...patch }))
  const setFilter = (i: number, patch: Partial<MetricForm['filters'][number]>) => setForm((f) => ({ ...f, filters: f.filters.map((x, j) => (j === i ? { ...x, ...patch } : x)) }))
  const fieldChoices = fieldsForAgg(entity, form.agg)

  const save = async () => {
    setShowHints(true)
    if (problems.length > 0) return
    setBusy(true)
    setError(null)
    try {
      const def = formToDefinition(form, entity)
      if (editingKey) await api.updateMetric(projectId, editingKey, def)
      else await api.createMetric(projectId, def)
      await onSaved()
    } catch (err) {
      setError(errorMessage(err, 'Could not save the metric'))
    } finally {
      setBusy(false)
    }
  }

  const err = (id: string, field: string) => (hint(field) ? <span id={`${id}-err`} className="error-text small-text">{hint(field)}</span> : null)
  return (
    <form className="card" aria-label={editingKey ? `Edit metric ${editingKey}` : 'New metric'} onSubmit={(e) => { e.preventDefault(); void save() }} noValidate>
      <div className="field-grid">
        <label htmlFor="m-key">Key</label>
        <input id="m-key" value={form.key} disabled={editingKey !== null} onChange={(e) => set({ key: e.target.value })} aria-invalid={!!hint('key')} aria-describedby="m-key-err" autoComplete="off" />
        {err('m-key', 'key')}
        <label htmlFor="m-label">Name</label>
        <input id="m-label" value={form.label} onChange={(e) => set({ label: e.target.value })} aria-invalid={!!hint('label')} aria-describedby="m-label-err" autoComplete="off" />
        {err('m-label', 'label')}
        <label htmlFor="m-entity">Entity</label>
        <select id="m-entity" value={form.entity} onChange={(e) => set({ entity: e.target.value, field: '', group_by: '', filters: [] })}>
          {entities.map((e) => <option key={e.name} value={e.name}>{e.name}</option>)}
        </select>
        <label htmlFor="m-agg">Calculation</label>
        <select id="m-agg" value={form.agg} onChange={(e) => set({ agg: e.target.value, field: '' })}>
          {AGGS.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
        </select>
        <label htmlFor="m-field">Field{form.agg === 'count' ? ' (optional)' : ''}</label>
        <select id="m-field" value={form.field} onChange={(e) => set({ field: e.target.value })} aria-invalid={!!hint('field')} aria-describedby="m-field-err">
          <option value="">{form.agg === 'count' ? 'All records' : 'Choose a field'}</option>
          {fieldChoices.map((f) => <option key={f.name} value={f.name}>{f.name}{isNumericType(f.type) ? '' : ` (${f.type})`}</option>)}
        </select>
        {err('m-field', 'field')}
        <label htmlFor="m-group">Group by (optional)</label>
        <select id="m-group" value={form.group_by} onChange={(e) => set({ group_by: e.target.value })}>
          <option value="">No grouping</option>
          {scalarFields(entity).map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
        </select>
        <label htmlFor="m-unit">Unit (optional)</label>
        <input id="m-unit" value={form.unit} maxLength={30} onChange={(e) => set({ unit: e.target.value })} autoComplete="off" />
      </div>
      <fieldset>
        <legend>Filters</legend>
        {form.filters.length === 0 && <p className="small-text muted">No filters: every record counts.</p>}
        {form.filters.map((f, i) => {
          const type = entity?.fields.find((x) => x.name === f.field)?.type ?? 'string'
          return (
            <div key={i} className="hstack" role="group" aria-label={`Filter ${i + 1}`}>
              <select aria-label={`Filter ${i + 1} field`} value={f.field} onChange={(e) => setFilter(i, { field: e.target.value })}>
                <option value="">Field</option>
                {scalarFields(entity).map((x) => <option key={x.name} value={x.name}>{x.name}</option>)}
              </select>
              <select aria-label={`Filter ${i + 1} operator`} value={f.op} onChange={(e) => setFilter(i, { op: e.target.value })}>
                {opsFor(type).map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
              </select>
              <input aria-label={`Filter ${i + 1} value`} value={f.value} placeholder={f.op === 'in' ? 'a, b, c' : 'value'} onChange={(e) => setFilter(i, { value: e.target.value })} autoComplete="off" />
              <button type="button" className="btn btn-sm" aria-label={`Remove filter ${i + 1}`} onClick={() => set({ filters: form.filters.filter((_, j) => j !== i) })}>Remove</button>
              {hint(`filter-${i}`) && <span className="error-text small-text">{hint(`filter-${i}`)}</span>}
            </div>
          )
        })}
        <button type="button" className="btn btn-sm" disabled={form.filters.length >= 10} onClick={() => set({ filters: [...form.filters, { field: '', op: 'eq', value: '' }] })}>Add filter</button>
      </fieldset>
      {error && <p role="alert" className="error-text" data-testid="metric-form-error">{error}</p>}
      <div className="hstack">
        <button type="submit" disabled={busy}>{editingKey ? 'Save metric' : 'Create metric'}</button>
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  )
}

// -- reports -----------------------------------------------------------------------------------

function ReportsTab({ projectId, metrics, reports, onChanged }: { projectId: string; metrics: MetricRead[]; reports: ReportRead[]; onChanged: () => Promise<void> }) {
  const [editing, setEditing] = useState<{ id: string | null; form: ReportForm } | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  const remove = async (id: string) => {
    setError(null)
    try {
      await api.deleteReport(projectId, id)
      setConfirmDelete(null)
      if (openId === id) setOpenId(null)
      await onChanged()
    } catch (err) {
      setConfirmDelete(null)
      setError(errorMessage(err, 'Could not delete the report'))
    }
  }

  const open = reports.find((r) => r.id === openId)
  return (
    <>
      <div className="hstack">
        <h2 className="grow">Reports</h2>
        {!editing && <button type="button" disabled={metrics.length === 0} onClick={() => { setError(null); setEditing({ id: null, form: emptyReportForm() }) }}>New report</button>}
      </div>
      {metrics.length === 0 && <p className="small-text muted" data-testid="reports-need-metrics">Create a metric first; a report collects metrics.</p>}
      {error && <p role="alert" className="error-text" data-testid="reports-action-error">{error}</p>}
      {editing && (
        <ReportFormView projectId={projectId} metrics={metrics} editingId={editing.id} initial={editing.form} onCancel={() => setEditing(null)}
          onSaved={async () => { setEditing(null); await onChanged() }} />
      )}
      {reports.length === 0 && !editing && metrics.length > 0 && (
        <div className="card empty-hero" data-testid="reports-empty"><h2>No reports yet</h2><p>A report gathers several metrics and runs on a schedule you choose.</p></div>
      )}
      {reports.length > 0 && (
        <ul className="ai-list" aria-label="Reports">
          {reports.map((r) => (
            <li key={r.id} className="card" data-testid="report-row">
              <div className="hstack">
                <div className="grow">
                  <h3>{r.name}</h3>
                  <p className="small-text">{cronLabel(r.schedule)} ({r.timezone}), {r.enabled ? 'on' : 'paused'}. Metrics: {r.metric_keys.join(', ')}</p>
                </div>
              </div>
              <div className="hstack">
                <button type="button" className="btn btn-sm" aria-expanded={openId === r.id} aria-label={`${openId === r.id ? 'Hide' : 'Open'} report ${r.name}`} onClick={() => setOpenId(openId === r.id ? null : r.id)}>
                  {openId === r.id ? 'Hide' : 'Open'}
                </button>
                <button type="button" className="btn btn-sm" aria-label={`Edit report ${r.name}`} onClick={() => { setError(null); setEditing({ id: r.id, form: reportToForm(r) }) }}>Edit</button>
                {confirmDelete === r.id ? (
                  <>
                    <button type="button" className="btn btn-sm" onClick={() => void remove(r.id)}>Confirm delete {r.name}</button>
                    <button type="button" className="btn btn-sm" onClick={() => setConfirmDelete(null)}>Keep it</button>
                  </>
                ) : (
                  <button type="button" className="btn btn-sm" aria-label={`Delete report ${r.name}`} onClick={() => setConfirmDelete(r.id)}>Delete</button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {open && <ReportDetail projectId={projectId} report={open} metrics={metrics} />}
    </>
  )
}

function ReportFormView({ projectId, metrics, editingId, initial, onCancel, onSaved }: {
  projectId: string; metrics: MetricRead[]; editingId: string | null; initial: ReportForm; onCancel: () => void; onSaved: () => Promise<void>
}) {
  const [form, setForm] = useState<ReportForm>(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showHints, setShowHints] = useState(false)
  const problems = validateReportForm(form)
  const hint = (field: string) => (showHints ? problems.filter((p) => p.field === field).map((p) => p.message).join(' ') : '')
  const preset = presetOf(form.schedule)
  const [custom, setCustom] = useState(preset === 'custom')

  const save = async () => {
    setShowHints(true)
    if (problems.length > 0) return
    setBusy(true)
    setError(null)
    try {
      if (editingId) await api.updateReport(projectId, editingId, formToReport(form))
      else await api.createReport(projectId, formToReport(form))
      await onSaved()
    } catch (err) {
      setError(errorMessage(err, 'Could not save the report'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card" aria-label={editingId ? 'Edit report' : 'New report'} onSubmit={(e) => { e.preventDefault(); void save() }} noValidate>
      <div className="field-grid">
        <label htmlFor="r-name">Name</label>
        <input id="r-name" value={form.name} maxLength={120} onChange={(e) => setForm({ ...form, name: e.target.value })} aria-invalid={!!hint('name')} aria-describedby="r-name-err" autoComplete="off" />
        {hint('name') && <span id="r-name-err" className="error-text small-text">{hint('name')}</span>}
        <label htmlFor="r-sched">Schedule</label>
        <select id="r-sched" value={custom ? 'custom' : preset} onChange={(e) => {
          if (e.target.value === 'custom') setCustom(true)
          else { setCustom(false); setForm({ ...form, schedule: CRON_PRESETS.find((p) => p.id === e.target.value)!.cron }) }
        }}>
          {CRON_PRESETS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          <option value="custom">Custom…</option>
        </select>
        {custom && (
          <>
            <label htmlFor="r-cron">Custom schedule</label>
            <input id="r-cron" value={form.schedule} onChange={(e) => setForm({ ...form, schedule: e.target.value })} aria-invalid={!!hint('schedule')} aria-describedby="r-cron-err" autoComplete="off" spellCheck={false} />
          </>
        )}
        {hint('schedule') && <span id="r-cron-err" className="error-text small-text">{hint('schedule')}</span>}
        <label htmlFor="r-tz">Time zone</label>
        <input id="r-tz" list="r-tz-list" value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} autoComplete="off" />
        <datalist id="r-tz-list">{TIMEZONES.map((z) => <option key={z} value={z} />)}</datalist>
      </div>
      <fieldset aria-describedby="r-metrics-err">
        <legend>Metrics in this report</legend>
        {metrics.map((m) => (
          <label key={m.key} className="hstack">
            <input type="checkbox" checked={form.metric_keys.includes(m.key)} onChange={() => setForm({ ...form, metric_keys: toggleKey(form.metric_keys, m.key) })} />
            {m.definition.label}
          </label>
        ))}
        {hint('metrics') && <span id="r-metrics-err" className="error-text small-text">{hint('metrics')}</span>}
      </fieldset>
      <label className="hstack">
        <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
        Run on this schedule
      </label>
      {error && <p role="alert" className="error-text" data-testid="report-form-error">{error}</p>}
      <div className="hstack">
        <button type="submit" disabled={busy}>{editingId ? 'Save report' : 'Create report'}</button>
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  )
}

function ReportDetail({ projectId, report, metrics }: { projectId: string; report: ReportRead; metrics: MetricRead[] }) {
  const [live, setLive] = useState<{ status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; value: ReportValue }>({ status: 'loading' })
  const [runs, setRuns] = useState<ReportRunRead[]>([])
  const [runsError, setRunsError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadAll = useCallback(async () => {
    setLive({ status: 'loading' })
    setRunsError(null)
    await Promise.all([
      api.getReportValue(projectId, report.id)
        .then((value) => setLive({ status: 'ready', value }))
        .catch((err: unknown) => setLive({ status: 'error', message: errorMessage(err, 'Could not compute this report') })),
      api.listReportRuns(projectId, report.id)
        .then((p) => setRuns(p.items))
        .catch((err: unknown) => setRunsError(errorMessage(err, 'Could not load the run history'))),
    ])
  }, [projectId, report.id])

  useEffect(() => { void loadAll() }, [loadAll])

  const runNow = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.runReport(projectId, report.id)
      await loadAll()
    } catch (err) {
      setError(errorMessage(err, 'Could not run the report'))
    } finally {
      setBusy(false)
    }
  }

  const label = (key: string) => metrics.find((m) => m.key === key)?.definition.label ?? key
  return (
    <section className="card" aria-label={`Report ${report.name}`} data-testid="report-detail">
      <div className="hstack">
        <h3 className="grow">{report.name}</h3>
        <button type="button" disabled={busy} onClick={() => void runNow()}>Run now</button>
      </div>
      {error && <p role="alert" className="error-text" data-testid="report-run-error">{error}</p>}
      <h4>Live values</h4>
      {live.status === 'loading' && <p className="muted">Computing…</p>}
      {live.status === 'error' && <p role="alert" className="error-text" data-testid="report-value-error">{live.message}</p>}
      {live.status === 'ready' && (
        <dl>
          {report.metric_keys.map((k) => {
            const slot = slotOf(live.value.values, k)
            const unit = unitOf(metrics, k)
            return (
              <div key={k} className="hstack">
                <dt>{label(k)}</dt>
                <dd data-testid={`report-value-${k}`}>{slotText(slot, unit)}</dd>
              </div>
            )
          })}
        </dl>
      )}
      <h4>Run history</h4>
      {runsError && <p role="alert" className="error-text">{runsError}</p>}
      {!runsError && runs.length === 0 && <p className="muted" data-testid="report-no-runs">No runs yet. Use Run now to store one.</p>}
      {runs.length > 0 && (
        <ul aria-label="Run history">
          {runs.map((run) => (
            <li key={run.id} data-testid="report-run">
              <span>{run.scheduled_for.slice(0, 16).replace('T', ' ')} UTC, {run.status}: </span>
              {report.metric_keys.map((k) => `${label(k)} ${slotText(slotOf(run.values, k), unitOf(metrics, k))}`).join('; ')}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
