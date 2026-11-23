import { useCallback, useEffect, useId, useMemo, useState } from 'react'
import { api, ApiError } from '../../api/client'
import { PreviewSessionGate } from '../preview/PreviewSessionGate'
import { usePreviewSession } from '../preview/usePreviewSession'
import type { PreviewSession } from '../preview/previewSession'
import { addDays, formatDay, formatInstant, localParts, parseBookingJson, parseLocalInput, type Booking, type Slot } from './calendarLogic'
import {
  adminErrorMessage, applyBooking, buildResourceCreate, buildResourceUpdate, describeCancellation, formatSchedule, freeGaps, groupSlots, kindFormOf, kindToSpec,
  MAX_KINDS, newKindForm, rulesFormOf, saveErrorMessage, validateKind, validateRange, validateRules, type Errors, type KindForm, type Obj, type ResourceRow, type RulesForm,
} from './bookingAdminLogic'

type Load<T> = { s: 'loading' } | { s: 'error'; m: string } | { s: 'ok'; v: T }
type Call = (method: string, path: string, body?: unknown) => Promise<{ status: number; json: unknown }>
const msg = (e: unknown, f: string) => (e instanceof Error ? e.message : f)
const ok = (s: number) => s >= 200 && s < 300

function Field({ label, error, children, hint }: { label: string; error?: string; hint?: string; children: (p: { id: string; 'aria-describedby'?: string; 'aria-invalid'?: boolean }) => React.ReactNode }) {
  const id = useId()
  const d = [error ? `${id}-e` : '', hint ? `${id}-h` : ''].filter(Boolean).join(' ') || undefined
  return (
    <div className="stack">
      <label htmlFor={id}>{label}</label>
      {children({ id, 'aria-describedby': d, 'aria-invalid': error ? true : undefined })}
      {hint && <span id={`${id}-h`} className="small-text muted">{hint}</span>}
      {error && <span id={`${id}-e`} className="error-text small-text" data-testid="bkadm-field-error">{error}</span>}
    </div>
  )
}

// ================================================================ rules + kinds (spec.packs.booking, builder API)

function RulesSection({ projectId, onKinds }: { projectId: string; onKinds: (k: { name: string; mode: string }[]) => void }) {
  const [state, setState] = useState<Load<{ packs: Obj | null; version: number }>>({ s: 'loading' })
  const [rules, setRules] = useState<RulesForm | null>(null)
  const [kinds, setKinds] = useState<{ form: KindForm; base: Obj | null }[]>([])
  const [newMode, setNewMode] = useState<'slot' | 'range' | 'pool'>('slot')
  const [errors, setErrors] = useState<Errors>({})
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [conflict, setConflict] = useState(false)
  const [tick, setTick] = useState(0)

  const adopt = useCallback((packs: Obj | null, version: number) => {
    setState({ s: 'ok', v: { packs, version } })
    const b = (packs?.booking ?? null) as Obj | null
    setRules(b ? rulesFormOf(b) : null)
    const ks = b && Array.isArray(b.kinds) ? (b.kinds as Obj[]) : []
    setKinds(ks.map((k) => ({ form: kindFormOf(k), base: k })))
    onKinds(ks.map((k) => ({ name: String(k.name), mode: String(k.mode) })))
  }, [onKinds])

  useEffect(() => {
    let dead = false
    setState({ s: 'loading' })
    api.getBlock(projectId, 'packs').then((r) => { if (!dead) adopt((r.packs ?? null) as Obj | null, Number(r.version ?? 0)) })
      .catch((e) => { if (!dead) setState({ s: 'error', m: msg(e, 'Could not load the packs') }) })
    return () => { dead = true }
  }, [projectId, tick, adopt])

  const setR = (k: keyof RulesForm, v: string | boolean) => setRules((r) => (r ? { ...r, [k]: v } : r))
  const setK = (i: number, k: keyof KindForm, v: string) => setKinds((ks) => ks.map((x, j) => (j === i ? { ...x, form: { ...x.form, [k]: v } } : x)))

  async function save() {
    if (state.s !== 'ok' || !rules) return
    const errs: Errors = validateRules(rules)
    if (kinds.length === 0) errs.kinds = 'Declare at least one resource kind.'
    if (kinds.length > MAX_KINDS) errs.kinds = `At most ${MAX_KINDS} resource kinds.`
    kinds.forEach((k, i) => Object.assign(errs, validateKind(k.form, i, kinds.filter((_, j) => j < i).map((x) => x.form.name))))
    setErrors(errs); setNotice(null); setSaveError(null); setConflict(false)
    if (Object.keys(errs).length) return
    setBusy(true)
    try {
      const packs = applyBooking(state.v.packs, rules, kinds.map((k) => kindToSpec(k.form, k.base ?? {})))
      const r = await api.putBlock(projectId, 'packs', { packs, expected_version: state.v.version })
      adopt((r.packs ?? packs) as Obj | null, Number(r.version ?? state.v.version + 1))
      setNotice('Saved. Regenerate and restart the preview for the running project to pick up the new rules.')
    } catch (e) {
      if (e instanceof ApiError) { setConflict(e.status === 409); setSaveError(saveErrorMessage(e.status, e.message, e.details)) }
      else setSaveError(msg(e, 'Could not save the packs'))
    } finally { setBusy(false) }
  }

  return (
    <section aria-labelledby="bkadm-rules-h" className="stack" data-testid="bkadm-rules">
      <h2 id="bkadm-rules-h">Rules and kinds</h2>
      <p className="muted small-text">These live in the project spec (packs.booking), not in the running API. Changes apply after the project is regenerated.</p>
      {state.s === 'loading' && <p role="status" className="muted" data-testid="bkadm-rules-loading">Loading the booking rules…</p>}
      {state.s === 'error' && <p role="alert" className="error-text" data-testid="bkadm-rules-error">{state.m}</p>}
      {state.s === 'ok' && !rules && <p className="muted" data-testid="bkadm-rules-empty">This project has no booking pack. Add one in the spec (packs.booking) to manage bookings.</p>}
      {state.s === 'ok' && rules && (
        <form className="stack" onSubmit={(e) => { e.preventDefault(); void save() }} aria-label="Booking rules" data-testid="bkadm-rules-form" noValidate>
          <fieldset className="stack">
            <legend>Roles</legend>
            <Field label="Read roles" error={errors.read_roles} hint="Comma separated. Empty means any signed-in user.">{(p) => <input {...p} value={rules.read_roles} onChange={(e) => setR('read_roles', e.target.value)} data-testid="bkadm-read-roles" />}</Field>
            <Field label="Book roles" error={errors.book_roles} hint="Comma separated. Empty means any signed-in user.">{(p) => <input {...p} value={rules.book_roles} onChange={(e) => setR('book_roles', e.target.value)} data-testid="bkadm-book-roles" />}</Field>
            <Field label="Manage roles" error={errors.manage_roles} hint="At least one. Managers create resources and see every booking.">{(p) => <input {...p} value={rules.manage_roles} onChange={(e) => setR('manage_roles', e.target.value)} data-testid="bkadm-manage-roles" />}</Field>
            <label className="hstack"><input type="checkbox" checked={rules.own_only} onChange={(e) => setR('own_only', e.target.checked)} data-testid="bkadm-own-only" /> Own bookings only (people outside the manage roles see only their own)</label>
          </fieldset>
          <fieldset className="stack">
            <legend>Holds and horizon</legend>
            <Field label="Hold time (seconds)" error={errors.hold_ttl_seconds} hint="How long a hold lasts before it expires. 1 to 86400.">{(p) => <input {...p} inputMode="numeric" value={rules.hold_ttl_seconds} onChange={(e) => setR('hold_ttl_seconds', e.target.value)} data-testid="bkadm-hold-ttl" />}</Field>
            <Field label="Booking horizon (days)" error={errors.max_horizon_days} hint="How far ahead people can book. 1 to 730.">{(p) => <input {...p} inputMode="numeric" value={rules.max_horizon_days} onChange={(e) => setR('max_horizon_days', e.target.value)} data-testid="bkadm-horizon" />}</Field>
          </fieldset>
          <fieldset className="stack">
            <legend>Cancellation</legend>
            <Field label="Free cancellation until (hours before the start)" error={errors.free_until_hours}>{(p) => <input {...p} inputMode="numeric" value={rules.free_until_hours} onChange={(e) => setR('free_until_hours', e.target.value)} data-testid="bkadm-free-hours" />}</Field>
            <Field label="Late cancellation fee (minor units, e.g. cents)" error={errors.fee_minor} hint="A whole number. 2500 with USD is 25.00. Recorded only, nothing is charged.">{(p) => <input {...p} inputMode="numeric" value={rules.fee_minor} onChange={(e) => setR('fee_minor', e.target.value)} data-testid="bkadm-fee" />}</Field>
            <Field label="Currency" error={errors.currency} hint="3 letter ISO code, upper case.">{(p) => <input {...p} value={rules.currency} maxLength={3} onChange={(e) => setR('currency', e.target.value)} data-testid="bkadm-currency" />}</Field>
            <p className="small-text" data-testid="bkadm-cancel-summary">{describeCancellation(rules.free_until_hours, rules.fee_minor, rules.currency)}</p>
          </fieldset>

          <h3>Resource kinds</h3>
          {errors.kinds && <p role="alert" className="error-text" data-testid="bkadm-kinds-error">{errors.kinds}</p>}
          {kinds.map((k, i) => (
            <fieldset key={i} className="stack" data-testid="bkadm-kind">
              <legend>{k.form.name || 'New kind'} ({k.form.mode})</legend>
              <Field label="Name" error={errors[`kinds[${i}].name`]} hint={k.base ? 'Existing kinds keep their name and mode.' : undefined}>{(p) => <input {...p} value={k.form.name} readOnly={!!k.base} onChange={(e) => setK(i, 'name', e.target.value)} data-testid="bkadm-kind-name" />}</Field>
              <Field label="Time zone" error={errors[`kinds[${i}].timezone`]}>{(p) => <input {...p} value={k.form.timezone} onChange={(e) => setK(i, 'timezone', e.target.value)} data-testid="bkadm-kind-tz" />}</Field>
              {k.form.mode === 'slot' && (
                <>
                  <Field label="Slot length (minutes)" error={errors[`kinds[${i}].slot_minutes`]}>{(p) => <input {...p} inputMode="numeric" value={k.form.slot_minutes} onChange={(e) => setK(i, 'slot_minutes', e.target.value)} data-testid="bkadm-kind-slot" />}</Field>
                  <Field label="Weekly schedule" error={errors[`kinds[${i}].schedule`]} hint="One line per weekday, for example: mon 09:00-12:00, 13:00-17:00">{(p) => <textarea {...p} rows={5} value={k.form.schedule} onChange={(e) => setK(i, 'schedule', e.target.value)} data-testid="bkadm-kind-schedule" />}</Field>
                </>
              )}
              {k.form.mode !== 'slot' && (
                <>
                  <Field label="Minimum minutes" error={errors[`kinds[${i}].min_minutes`]}>{(p) => <input {...p} inputMode="numeric" value={k.form.min_minutes} onChange={(e) => setK(i, 'min_minutes', e.target.value)} data-testid="bkadm-kind-min" />}</Field>
                  <Field label="Maximum minutes">{(p) => <input {...p} inputMode="numeric" value={k.form.max_minutes} onChange={(e) => setK(i, 'max_minutes', e.target.value)} data-testid="bkadm-kind-max" />}</Field>
                </>
              )}
              {k.form.mode === 'pool' && <Field label="Capacity (units)" error={errors[`kinds[${i}].capacity`]}>{(p) => <input {...p} inputMode="numeric" value={k.form.capacity} onChange={(e) => setK(i, 'capacity', e.target.value)} data-testid="bkadm-kind-capacity" />}</Field>}
              <button type="button" className="outline small" onClick={() => setKinds((ks) => ks.filter((_, j) => j !== i))} data-testid="bkadm-kind-remove" aria-label={`Remove kind ${k.form.name || i + 1}`}>Remove kind</button>
            </fieldset>
          ))}
          <div className="hstack">
            <label htmlFor="bkadm-new-mode">Mode of a new kind</label>
            <select id="bkadm-new-mode" value={newMode} onChange={(e) => setNewMode(e.target.value as 'slot' | 'range' | 'pool')} data-testid="bkadm-new-mode">
              <option value="slot">slot (fixed slots)</option><option value="range">range (any time range)</option><option value="pool">pool (quantity)</option>
            </select>
            <button type="button" className="outline small" onClick={() => setKinds((ks) => [...ks, { form: newKindForm(newMode), base: null }])} data-testid="bkadm-kind-add">Add kind</button>
          </div>

          {notice && <p role="status" data-testid="bkadm-rules-notice">{notice}</p>}
          {saveError && <p role="alert" className="error-text" data-testid="bkadm-rules-save-error">{saveError}</p>}
          <div className="hstack">
            <button type="submit" disabled={busy} data-testid="bkadm-rules-save">{busy ? 'Saving…' : 'Save rules'}</button>
            {conflict && <button type="button" className="outline" onClick={() => { setSaveError(null); setConflict(false); setTick((n) => n + 1) }} data-testid="bkadm-rules-reload">Reload latest</button>}
          </div>
        </form>
      )}
    </section>
  )
}

// ================================================================ resources (generated routes)

function ResourcesSection({ call, resources, reload, specKinds }: { call: Call; resources: Load<{ items: ResourceRow[]; total?: number }>; reload: () => void; specKinds: { name: string; mode: string }[] }) {
  const items = resources.s === 'ok' ? resources.v.items : []
  const kindNames = useMemo(() => [...new Set([...specKinds.map((k) => k.name), ...items.map((r) => r.kind)])], [specKinds, items])
  const modeOf = (kind: string) => (specKinds.find((k) => k.name === kind)?.mode ?? items.find((r) => r.kind === kind)?.mode ?? null) as 'slot' | 'range' | 'pool' | null
  const [filter, setFilter] = useState('')
  const [form, setForm] = useState({ kind: '', name: '', timezone: '', capacity: '', schedule: '', active: true })
  const [editing, setEditing] = useState<string | null>(null)
  const [edit, setEdit] = useState({ name: '', timezone: '', schedule: '', active: true })
  const [confirmOff, setConfirmOff] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const kind = form.kind || kindNames[0] || ''
  const mode = modeOf(kind)
  const shown = items.filter((r) => !filter || r.kind === filter)

  async function run(fn: () => Promise<{ status: number; json: unknown }>, done: string, after?: () => void) {
    setBusy(true); setError(null); setNotice(null)
    try {
      const r = await fn()
      if (ok(r.status)) { setNotice(done); after?.(); reload() } else setError(adminErrorMessage(r.status, r.json))
    } catch (e) { setError(msg(e, 'Could not reach the booking API')) } finally { setBusy(false) }
  }
  function create(e: React.FormEvent) {
    e.preventDefault()
    const b = buildResourceCreate({ ...form, kind }, mode)
    if (!b.body) { setError(b.error ?? 'Check the form.'); setNotice(null); return }
    void run(() => call('POST', '/booking/resources', b.body), `Created ${String(b.body.name)}.`, () => setForm({ kind: '', name: '', timezone: '', capacity: '', schedule: '', active: true }))
  }
  function startEdit(r: ResourceRow) { setEditing(r.id); setConfirmOff(null); setError(null); setNotice(null); setEdit({ name: r.name, timezone: r.timezone, schedule: formatSchedule(r.schedule), active: r.active }) }
  function saveEdit(e: React.FormEvent, r: ResourceRow) {
    e.preventDefault()
    const b = buildResourceUpdate(r, edit)
    if (!b.body) { setError(b.error ?? 'Check the form.'); return }
    void run(() => call('PATCH', `/booking/resources/${encodeURIComponent(r.id)}`, b.body), `Saved ${edit.name.trim()}.`, () => setEditing(null))
  }
  const setActive = (r: ResourceRow, active: boolean) => run(() => call('PATCH', `/booking/resources/${encodeURIComponent(r.id)}`, { active }), `${r.name} ${active ? 'enabled' : 'disabled'}.`, () => setConfirmOff(null))
  const editRow = items.find((r) => r.id === editing) ?? null

  return (
    <section aria-labelledby="bkadm-res-h" className="stack" data-testid="bkadm-resources">
      <h2 id="bkadm-res-h">Resources</h2>
      {resources.s === 'loading' && <p role="status" className="muted" data-testid="bkadm-res-loading">Loading resources…</p>}
      {resources.s === 'error' && <p role="alert" className="error-text" data-testid="bkadm-res-error">{resources.m}</p>}
      {resources.s === 'ok' && (resources.v.total ?? 0) > items.length && <p role="alert" className="error-text" data-testid="bkadm-res-truncated">Only the first {items.length} of {resources.v.total} resources are listed.</p>}
      {resources.s === 'ok' && items.length === 0 && <p className="muted" data-testid="bkadm-res-empty">No resources yet. Create one below.</p>}
      {resources.s === 'ok' && items.length > 0 && (
        <>
          <div className="hstack">
            <label htmlFor="bkadm-filter">Filter by kind</label>
            <select id="bkadm-filter" value={filter} onChange={(e) => setFilter(e.target.value)} data-testid="bkadm-filter">
              <option value="">All kinds</option>{kindNames.map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
          </div>
          <div className="stage-table-wrap" role="region" aria-label="Resource list" tabIndex={0}>
            <table className="stage-table" data-testid="bkadm-res-table">
              <thead><tr><th scope="col">Name</th><th scope="col">Kind</th><th scope="col">Mode</th><th scope="col">Time zone</th><th scope="col">Status</th><th scope="col">Actions</th></tr></thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.id} data-testid="bkadm-res-row" data-active={r.active}>
                    <th scope="row">{r.name}</th><td>{r.kind}</td><td>{r.mode}{r.mode === 'pool' ? ` (${r.capacity})` : ''}</td><td>{r.timezone}</td><td>{r.active ? 'Active' : 'Disabled'}</td>
                    <td className="hstack">
                      <button type="button" className="outline small" onClick={() => startEdit(r)} data-testid="bkadm-res-edit" aria-label={`Edit ${r.name}`}>Edit</button>
                      {r.active
                        ? <button type="button" className="outline small" disabled={busy} onClick={() => setConfirmOff(r.id)} data-testid="bkadm-res-disable" aria-label={`Disable ${r.name}`}>Disable</button>
                        : <button type="button" className="outline small" disabled={busy} onClick={() => void setActive(r, true)} data-testid="bkadm-res-enable" aria-label={`Enable ${r.name}`}>Enable</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {confirmOff && (
        <div role="group" aria-label="Confirm disable" className="stack" data-testid="bkadm-disable-confirm">
          <p className="small-text">Disable {items.find((r) => r.id === confirmOff)?.name}? New bookings are refused; bookings already made stay as they are.</p>
          <div className="hstack">
            <button type="button" disabled={busy} onClick={() => { const r = items.find((x) => x.id === confirmOff); if (r) void setActive(r, false) }} data-testid="bkadm-disable-yes">Yes, disable</button>
            <button type="button" className="outline" onClick={() => setConfirmOff(null)} data-testid="bkadm-disable-no">Keep it enabled</button>
          </div>
        </div>
      )}
      {editRow && (
        <form className="stack" onSubmit={(e) => saveEdit(e, editRow)} aria-label={`Edit ${editRow.name}`} data-testid="bkadm-edit-form" noValidate>
          <h3>Edit {editRow.name}</h3>
          <Field label="Name">{(p) => <input {...p} value={edit.name} maxLength={120} onChange={(e) => setEdit({ ...edit, name: e.target.value })} data-testid="bkadm-edit-name" />}</Field>
          <Field label="Time zone">{(p) => <input {...p} value={edit.timezone} onChange={(e) => setEdit({ ...edit, timezone: e.target.value })} data-testid="bkadm-edit-tz" />}</Field>
          {editRow.mode === 'slot' && <Field label="Weekly schedule" hint="One line per weekday, for example: mon 09:00-12:00, 13:00-17:00">{(p) => <textarea {...p} rows={4} value={edit.schedule} onChange={(e) => setEdit({ ...edit, schedule: e.target.value })} data-testid="bkadm-edit-schedule" />}</Field>}
          <label className="hstack"><input type="checkbox" checked={edit.active} onChange={(e) => setEdit({ ...edit, active: e.target.checked })} data-testid="bkadm-edit-active" /> Active (bookable)</label>
          <div className="hstack">
            <button type="submit" disabled={busy} data-testid="bkadm-edit-save">Save changes</button>
            <button type="button" className="outline" onClick={() => setEditing(null)} data-testid="bkadm-edit-cancel">Cancel</button>
          </div>
        </form>
      )}

      <form className="stack" onSubmit={create} aria-label="Create a resource" data-testid="bkadm-create-form" noValidate>
        <h3>New resource</h3>
        {kindNames.length === 0 ? <p className="muted small-text" data-testid="bkadm-no-kinds">Declare a kind under Rules and kinds first.</p> : (
          <>
            <Field label="Kind">{(p) => <select {...p} value={kind} onChange={(e) => setForm({ ...form, kind: e.target.value })} data-testid="bkadm-create-kind">{kindNames.map((k) => <option key={k} value={k}>{k}{modeOf(k) ? ` (${modeOf(k)})` : ''}</option>)}</select>}</Field>
            <Field label="Name">{(p) => <input {...p} value={form.name} maxLength={120} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="bkadm-create-name" />}</Field>
            <Field label="Time zone (optional)" hint="Defaults to the kind's zone.">{(p) => <input {...p} value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} data-testid="bkadm-create-tz" />}</Field>
            {mode === 'pool' && <Field label="Capacity (optional)" hint="Defaults to the kind's capacity.">{(p) => <input {...p} inputMode="numeric" value={form.capacity} onChange={(e) => setForm({ ...form, capacity: e.target.value })} data-testid="bkadm-create-capacity" />}</Field>}
            {mode === 'slot' && <Field label="Weekly schedule (optional)" hint="Defaults to the kind's schedule.">{(p) => <textarea {...p} rows={3} value={form.schedule} onChange={(e) => setForm({ ...form, schedule: e.target.value })} data-testid="bkadm-create-schedule" />}</Field>}
            <label className="hstack"><input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} data-testid="bkadm-create-active" /> Active (bookable)</label>
            <button type="submit" disabled={busy} data-testid="bkadm-create-submit">{busy ? 'Working…' : 'Create resource'}</button>
          </>
        )}
      </form>
      <div aria-live="polite">
        {notice && <p role="status" data-testid="bkadm-res-notice">{notice}</p>}
        {error && <p role="alert" className="error-text" data-testid="bkadm-res-action-error">{error}</p>}
      </div>
    </section>
  )
}

// ================================================================ availability

function AvailabilitySection({ call, resources, now }: { call: Call; resources: ResourceRow[]; now: () => number }) {
  const [id, setId] = useState('')
  const res = resources.find((r) => r.id === id) ?? resources[0] ?? null
  const tz = res?.timezone ?? 'UTC'
  const today = localParts(now(), tz).date
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [ls, setLs] = useState(''), [le, setLe] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [days, setDays] = useState<ReturnType<typeof groupSlots> | null>(null)
  const [text, setText] = useState<string | null>(null)
  const [gaps, setGaps] = useState<{ from: string; to: string }[] | null>(null)
  const f = from || today, t = to || addDays(today, 6)
  const reset = () => { setDays(null); setText(null); setGaps(null); setErr(null) }

  async function check(e: React.FormEvent) {
    e.preventDefault(); reset()
    if (!res) return
    const rid = encodeURIComponent(res.id)
    let path = ''
    let s: string | null = null, en: string | null = null
    if (res.mode === 'slot') {
      const bad = validateRange(f, t); if (bad) { setErr(bad); return }
      path = `/booking/resources/${rid}/availability?from=${f}&to=${t}&include_taken=true`
    } else {
      s = parseLocalInput(ls, tz); en = parseLocalInput(le, tz)
      if (!s || !en || Date.parse(en) <= Date.parse(s)) { setErr('Enter a start and an end, the end after the start.'); return }
      path = res.mode === 'pool'
        ? `/booking/resources/${rid}/capacity?starts_at=${encodeURIComponent(s)}&ends_at=${encodeURIComponent(en)}`
        : `/booking/bookings?resource_id=${rid}&from=${encodeURIComponent(s)}&to=${encodeURIComponent(en)}&limit=200`
    }
    setBusy(true)
    try {
      const r = await call('GET', path)
      if (!ok(r.status)) { setErr(adminErrorMessage(r.status, r.json)); return }
      if (res.mode === 'slot') setDays(groupSlots(((r.json as { slots?: Slot[] }).slots ?? []), tz))
      else if (res.mode === 'pool') { const j = r.json as { capacity: number; booked: number; free: number }; setText(`Capacity ${j.capacity}, booked ${j.booked}, free ${j.free} in that window.`) }
      else {
        const page = r.json as { items?: Booking[]; total?: number }
        const active = (page.items ?? []).filter((b) => b.status === 'confirmed' || b.status === 'held')
        if ((page.total ?? 0) > (page.items ?? []).length) setErr(`Only the first ${(page.items ?? []).length} of ${page.total} bookings were read, so the free windows below may be wrong.`)
        setGaps(freeGaps(active, Date.parse(s as string), Date.parse(en as string)))
      }
    } catch (x) { setErr(msg(x, 'Could not reach the booking API')) } finally { setBusy(false) }
  }

  return (
    <section aria-labelledby="bkadm-av-h" className="stack" data-testid="bkadm-availability">
      <h2 id="bkadm-av-h">Availability</h2>
      {!res && <p className="muted" data-testid="bkadm-av-empty">Create a resource to check its availability.</p>}
      {res && (
        <form className="stack" onSubmit={(e) => void check(e)} aria-label="Check availability" data-testid="bkadm-av-form" noValidate>
          <Field label="Resource">{(p) => <select {...p} value={res.id} onChange={(e) => { setId(e.target.value); reset() }} data-testid="bkadm-av-resource">{resources.map((r) => <option key={r.id} value={r.id}>{r.name} ({r.kind}, {r.mode})</option>)}</select>}</Field>
          {res.mode === 'slot' ? (
            <>
              <Field label="From date">{(p) => <input {...p} type="date" value={f} onChange={(e) => setFrom(e.target.value)} data-testid="bkadm-av-from" />}</Field>
              <Field label="To date" hint="At most 31 days.">{(p) => <input {...p} type="date" value={t} onChange={(e) => setTo(e.target.value)} data-testid="bkadm-av-to" />}</Field>
            </>
          ) : (
            <>
              <Field label={`Starts (${tz})`}>{(p) => <input {...p} type="datetime-local" value={ls} onChange={(e) => setLs(e.target.value)} data-testid="bkadm-av-start" />}</Field>
              <Field label={`Ends (${tz})`}>{(p) => <input {...p} type="datetime-local" value={le} onChange={(e) => setLe(e.target.value)} data-testid="bkadm-av-end" />}</Field>
            </>
          )}
          <button type="submit" disabled={busy} data-testid="bkadm-av-check">{busy ? 'Checking…' : res.mode === 'pool' ? 'Check capacity' : 'Check availability'}</button>
        </form>
      )}
      {err && <p role="alert" className="error-text" data-testid="bkadm-av-error">{err}</p>}
      {text && <p role="status" data-testid="bkadm-av-capacity">{text}</p>}
      {days && days.length === 0 && <p className="muted" data-testid="bkadm-av-none">No slots in that range (the schedule has no opening windows there, or it is outside the booking horizon).</p>}
      {days && days.length > 0 && (
        <table className="stage-table" data-testid="bkadm-av-table" aria-label="Slots per day">
          <thead><tr><th scope="col">Day ({tz})</th><th scope="col">Free</th><th scope="col">Taken</th></tr></thead>
          <tbody>{days.map((d) => <tr key={d.day} data-testid="bkadm-av-day"><th scope="row">{formatDay(d.day)}</th><td data-testid="bkadm-av-free">{d.free.length ? `${d.free.length}: ${d.free.join(', ')}` : 'none'}</td><td data-testid="bkadm-av-taken">{d.taken.length ? `${d.taken.length}: ${d.taken.join(', ')}` : 'none'}</td></tr>)}</tbody>
        </table>
      )}
      {gaps && (gaps.length === 0
        ? <p className="muted" data-testid="bkadm-av-nogaps">Fully booked in that window.</p>
        : <ul data-testid="bkadm-av-gaps" aria-label="Free windows">{gaps.map((g) => <li key={g.from} data-testid="bkadm-av-gap">{formatInstant(g.from, tz)} to {formatInstant(g.to, tz)}</li>)}</ul>)}
    </section>
  )
}

// ================================================================ page

function ResourceAndAvailability({ session, specKinds, now }: { session: PreviewSession; specKinds: { name: string; mode: string }[]; now: () => number }) {
  const { request } = session
  const [resources, setResources] = useState<Load<{ items: ResourceRow[]; total?: number }>>({ s: 'loading' })
  const [tick, setTick] = useState(0)
  const call = useCallback<Call>(async (method, path, body) => {
    const r = await request(method, path, body)
    let json: unknown = null
    try { json = r.text ? parseBookingJson(r.text) : null } catch { json = null }
    return { status: r.status, json }
  }, [request])
  useEffect(() => {
    let dead = false
    call('GET', '/booking/resources?limit=200').then((r) => {
      if (dead) return
      setResources(ok(r.status) ? { s: 'ok', v: r.json as { items: ResourceRow[]; total?: number } } : { s: 'error', m: adminErrorMessage(r.status, r.json) })
    }).catch((e) => { if (!dead) setResources({ s: 'error', m: msg(e, 'Could not reach the booking API') }) })
    return () => { dead = true }
  }, [call, tick])
  return (
    <>
      <ResourcesSection call={call} resources={resources} reload={() => setTick((n) => n + 1)} specKinds={specKinds} />
      <AvailabilitySection call={call} resources={resources.s === 'ok' ? resources.v.items.filter((r) => r.active) : []} now={now} />
    </>
  )
}

export function BookingAdminPage({ projectId, session, now = Date.now }: { projectId: string; session?: PreviewSession; now?: () => number }) {
  const own = usePreviewSession(projectId, { disabled: !!session })
  const s = session ?? own
  const [specKinds, setSpecKinds] = useState<{ name: string; mode: string }[]>([])
  return (
    <section aria-labelledby="bkadm-h" data-testid="bookingadmin-page" className="stack">
      <h1 id="bkadm-h">Booking admin</h1>
      <p className="muted">Manage bookable resources, check availability and edit the cancellation and role rules of the booking pack.</p>
      <RulesSection key={projectId} projectId={projectId} onKinds={setSpecKinds} />
      <PreviewSessionGate session={s} prefix="bkadm">
        <ResourceAndAvailability key={projectId} session={s} specKinds={specKinds} now={now} />
      </PreviewSessionGate>
    </section>
  )
}
