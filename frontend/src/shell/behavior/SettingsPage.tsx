import { useState } from 'react'
import { api } from '../../api/client'
import type { ListBody, SequenceBody, SettingBody } from '../../api/types'
import {
  SETTING_TYPES, blankItem, blankList, blankSequence, blankSetting, listFromBody, listToBody, previewNumber,
  sequenceFromBody, sequenceToBody, settingFromBody, settingToBody,
  type ListRow, type SectionIssues, type SequenceRow, type SettingRow, type FieldErrors,
} from './formLogic'
import { useSection, type SectionConfig } from './useSection'
import { ConflictBanner, Field, IssueSummary, LoadFailed, SaveBar } from './ui'

const SETTINGS: SectionConfig<SettingRow, SettingBody> = {
  key: 'settings',
  load: async (id) => { const r = await api.getSettings(id); return { version: r.version, items: r.settings } },
  save: async (id, items, v) => { const r = await api.putSettings(id, items, v); return { version: r.version, items: r.settings } },
  fromBody: settingFromBody,
  toBody: settingToBody,
}
const SEQUENCES: SectionConfig<SequenceRow, SequenceBody> = {
  key: 'sequences',
  load: async (id) => { const r = await api.getSequences(id); return { version: r.version, items: r.sequences } },
  save: async (id, items, v) => { const r = await api.putSequences(id, items, v); return { version: r.version, items: r.sequences } },
  fromBody: sequenceFromBody,
  toBody: sequenceToBody,
}
const LISTS: SectionConfig<ListRow, ListBody> = {
  key: 'lists',
  load: async (id) => { const r = await api.getLists(id); return { version: r.version, items: r.lists } },
  save: async (id, items, v) => { const r = await api.putLists(id, items, v); return { version: r.version, items: r.lists } },
  fromBody: listFromBody,
  toBody: listToBody,
}

type Msgs = (i: number, field: string) => string[]
const msgsFor = (issues: SectionIssues, client: FieldErrors): Msgs => (i, field) => [
  ...(client[`${i}.${field}`] ? [client[`${i}.${field}`]] : []),
  ...(issues.rows[i]?.fields[field] ?? []),
]

const ROLES_HINT = 'Role names, separated by commas'

interface EditorProps<Row> {
  rows: Row[]
  msgs: Msgs
  issues: SectionIssues
  onEdit: (i: number, patch: Partial<Row>, field: string) => void
  onRemove: (i: number) => void
}

function RowIssues({ issues, i }: { issues: SectionIssues; i: number }) {
  const r = issues.rows[i]?.row ?? []
  return r.length ? <div role="alert" data-variant="danger" className="bh-alert">{r.join(' ')}</div> : null
}

function SettingsEditor({ rows, msgs, issues, onEdit, onRemove }: EditorProps<SettingRow>) {
  return (
    <>
      {rows.map((r, i) => {
        const id = `st-${r.k}`
        return (
          <fieldset key={r.k} className="card bh-row" data-testid="setting-row">
            <legend>{r.key || 'New setting'}</legend>
            <RowIssues issues={issues} i={i} />
            <div className="bh-grid">
              <Field id={`${id}-key`} label="Name" messages={msgs(i, 'key')}>
                {(p) => <input {...p} value={r.key} onChange={(e) => onEdit(i, { key: e.target.value }, 'key')} />}
              </Field>
              <Field id={`${id}-type`} label="Type" messages={msgs(i, 'type')}>
                {(p) => (
                  <select {...p} value={r.type} onChange={(e) => onEdit(i, { type: e.target.value }, 'type')}>
                    {SETTING_TYPES.map((t) => <option key={t}>{t}</option>)}
                  </select>
                )}
              </Field>
              <Field id={`${id}-default`} label="Default value" messages={msgs(i, 'default')}>
                {(p) =>
                  r.type === 'bool' ? (
                    <select {...p} value={r.default} onChange={(e) => onEdit(i, { default: e.target.value }, 'default')}>
                      <option value="">(not set)</option><option value="true">true</option><option value="false">false</option>
                    </select>
                  ) : (
                    <input {...p} value={r.default} onChange={(e) => onEdit(i, { default: e.target.value }, 'default')} />
                  )
                }
              </Field>
              {(r.type === 'int' || r.type === 'decimal') && (
                <>
                  <Field id={`${id}-min`} label="Minimum" messages={msgs(i, 'minimum')}>
                    {(p) => <input {...p} value={r.minimum} onChange={(e) => onEdit(i, { minimum: e.target.value }, 'minimum')} />}
                  </Field>
                  <Field id={`${id}-max`} label="Maximum" messages={msgs(i, 'maximum')}>
                    {(p) => <input {...p} value={r.maximum} onChange={(e) => onEdit(i, { maximum: e.target.value }, 'maximum')} />}
                  </Field>
                </>
              )}
              {r.type === 'string' && (
                <Field id={`${id}-len`} label="Longest allowed text" messages={msgs(i, 'max_length')}>
                  {(p) => <input {...p} inputMode="numeric" value={r.max_length} onChange={(e) => onEdit(i, { max_length: e.target.value }, 'max_length')} />}
                </Field>
              )}
              <Field id={`${id}-label`} label="Label" messages={msgs(i, 'label')}>
                {(p) => <input {...p} value={r.label} onChange={(e) => onEdit(i, { label: e.target.value }, 'label')} />}
              </Field>
              <Field id={`${id}-read`} label="Who can read it" hint={`${ROLES_HINT}. Empty: any signed-in caller`} messages={msgs(i, 'read_roles')}>
                {(p) => <input {...p} value={r.read_roles} onChange={(e) => onEdit(i, { read_roles: e.target.value }, 'read_roles')} />}
              </Field>
              <Field id={`${id}-edit`} label="Who can change it" hint={`${ROLES_HINT}. Empty: nobody`} messages={msgs(i, 'edit_roles')}>
                {(p) => <input {...p} value={r.edit_roles} onChange={(e) => onEdit(i, { edit_roles: e.target.value }, 'edit_roles')} />}
              </Field>
            </div>
            <button className="outline small" onClick={() => onRemove(i)} aria-label={`Remove setting ${r.key || i + 1}`}>Remove</button>
          </fieldset>
        )
      })}
    </>
  )
}

function SequencesEditor({ rows, msgs, issues, onEdit, onRemove }: EditorProps<SequenceRow>) {
  return (
    <>
      {rows.map((r, i) => {
        const id = `sq-${r.k}`
        return (
          <fieldset key={r.k} className="card bh-row" data-testid="sequence-row">
            <legend>{r.name || 'New sequence'}</legend>
            <RowIssues issues={issues} i={i} />
            <div className="bh-grid">
              <Field id={`${id}-name`} label="Name" messages={msgs(i, 'name')}>
                {(p) => <input {...p} value={r.name} onChange={(e) => onEdit(i, { name: e.target.value }, 'name')} />}
              </Field>
              <Field id={`${id}-prefix`} label="Prefix" messages={msgs(i, 'prefix')}>
                {(p) => <input {...p} value={r.prefix} onChange={(e) => onEdit(i, { prefix: e.target.value }, 'prefix')} />}
              </Field>
              <Field id={`${id}-pad`} label="Digits (padding)" messages={msgs(i, 'padding')}>
                {(p) => <input {...p} inputMode="numeric" value={r.padding} onChange={(e) => onEdit(i, { padding: e.target.value }, 'padding')} />}
              </Field>
              <Field id={`${id}-start`} label="First number" messages={msgs(i, 'start')}>
                {(p) => <input {...p} inputMode="numeric" value={r.start} onChange={(e) => onEdit(i, { start: e.target.value }, 'start')} />}
              </Field>
              <Field id={`${id}-view`} label="Who can see the counters" hint={`${ROLES_HINT}. Empty: nobody`} messages={msgs(i, 'view_roles')}>
                {(p) => <input {...p} value={r.view_roles} onChange={(e) => onEdit(i, { view_roles: e.target.value }, 'view_roles')} />}
              </Field>
            </div>
            <div className="bh-checks">
              <Field id={`${id}-tenant`} label="Separate counter per tenant" messages={msgs(i, 'per_tenant')}>
                {(p) => <input {...p} type="checkbox" checked={r.per_tenant} onChange={(e) => onEdit(i, { per_tenant: e.target.checked }, 'per_tenant')} />}
              </Field>
              <Field id={`${id}-year`} label="Start again every year" messages={msgs(i, 'reset_yearly')}>
                {(p) => <input {...p} type="checkbox" checked={r.reset_yearly} onChange={(e) => onEdit(i, { reset_yearly: e.target.checked }, 'reset_yearly')} />}
              </Field>
            </div>
            <p className="muted">Next number looks like <code data-testid="seq-preview">{previewNumber(r)}</code></p>
            <button className="outline small" onClick={() => onRemove(i)} aria-label={`Remove sequence ${r.name || i + 1}`}>Remove</button>
          </fieldset>
        )
      })}
    </>
  )
}

function ListsEditor({ rows, msgs, issues, onEdit, onRemove, onRows }: EditorProps<ListRow> & { onRows: (rows: ListRow[]) => void }) {
  const patchItem = (li: number, ii: number, patch: Partial<ListRow['items'][number]>, field: string) => {
    const items = rows[li].items.map((it, n) => (n === ii ? { ...it, ...patch } : it))
    onEdit(li, { items }, `items[${ii}].${field}`)
  }
  return (
    <>
      {rows.map((r, i) => {
        const id = `ls-${r.k}`
        return (
          <fieldset key={r.k} className="card bh-row" data-testid="list-row">
            <legend>{r.name || 'New list'}</legend>
            <RowIssues issues={issues} i={i} />
            <div className="bh-grid">
              <Field id={`${id}-name`} label="Name" messages={msgs(i, 'name')}>
                {(p) => <input {...p} value={r.name} onChange={(e) => onEdit(i, { name: e.target.value }, 'name')} />}
              </Field>
              <Field id={`${id}-label`} label="Label" messages={msgs(i, 'label')}>
                {(p) => <input {...p} value={r.label} onChange={(e) => onEdit(i, { label: e.target.value }, 'label')} />}
              </Field>
              <Field id={`${id}-max`} label="Most items" hint="Defaults plus entries tenants add" messages={msgs(i, 'max_items')}>
                {(p) => <input {...p} inputMode="numeric" value={r.max_items} onChange={(e) => onEdit(i, { max_items: e.target.value }, 'max_items')} />}
              </Field>
              <Field id={`${id}-edit`} label="Who can edit the list" hint={`${ROLES_HINT}. Empty: nobody`} messages={msgs(i, 'edit_roles')}>
                {(p) => <input {...p} value={r.edit_roles} onChange={(e) => onEdit(i, { edit_roles: e.target.value }, 'edit_roles')} />}
              </Field>
            </div>
            {(issues.rows[i]?.fields['items'] ?? []).length > 0 && (
              <div role="alert" data-variant="danger" className="bh-alert">{issues.rows[i].fields['items'].join(' ')}</div>
            )}
            <table className="bh-items">
              <caption>Default items of {r.name || 'this list'}</caption>
              <thead>
                <tr><th scope="col">Value</th><th scope="col">Label</th><th scope="col">Colour</th><th scope="col">Locked</th><th scope="col"><span className="sr-only">Remove</span></th></tr>
              </thead>
              <tbody>
                {r.items.map((it, ii) => {
                  const iid = `${id}-i${it.k}`
                  const m = (f: string) => msgs(i, `items[${ii}].${f}`)
                  return (
                    <tr key={it.k} data-testid="list-item-row">
                      <td><Field id={`${iid}-v`} label={`Value of item ${ii + 1}`} messages={m('value')}>{(p) => <input {...p} value={it.value} onChange={(e) => patchItem(i, ii, { value: e.target.value }, 'value')} />}</Field></td>
                      <td><Field id={`${iid}-l`} label={`Label of item ${ii + 1}`} messages={m('label')}>{(p) => <input {...p} value={it.label} onChange={(e) => patchItem(i, ii, { label: e.target.value }, 'label')} />}</Field></td>
                      <td><Field id={`${iid}-c`} label={`Colour of item ${ii + 1}`} messages={m('color')}>{(p) => <input {...p} placeholder="#1a2b3c" value={it.color} onChange={(e) => patchItem(i, ii, { color: e.target.value }, 'color')} />}</Field></td>
                      <td><Field id={`${iid}-k`} label={`Item ${ii + 1} locked`} messages={m('locked')}>{(p) => <input {...p} type="checkbox" checked={it.locked} onChange={(e) => patchItem(i, ii, { locked: e.target.checked }, 'locked')} />}</Field></td>
                      <td><button className="outline small" aria-label={`Remove item ${it.value || ii + 1}`} onClick={() => onRows(rows.map((x, n) => (n === i ? { ...x, items: x.items.filter((_, k) => k !== ii) } : x)))}>Remove</button></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            <div className="bh-actions">
              <button className="outline small" onClick={() => onRows(rows.map((x, n) => (n === i ? { ...x, items: [...x.items, blankItem()] } : x)))}>Add item</button>
              <button className="outline small" onClick={() => onRemove(i)} aria-label={`Remove list ${r.name || i + 1}`}>Remove list</button>
            </div>
          </fieldset>
        )
      })}
    </>
  )
}

const INTRO = {
  settings: 'Runtime settings are values your app\'s admins can change without a redeploy, such as a VAT rate or an approval threshold.',
  sequences: 'A sequence hands out gapless, formatted numbers such as INV-00042, one counter per tenant or year if you want.',
  lists: 'Tenant-editable lists are dropdown choices, such as order statuses, that each customer can extend or relabel within limits you set.',
} as const

type Tab = keyof typeof INTRO
const TABS: { id: Tab; label: string; one: string }[] = [
  { id: 'settings', label: 'Settings', one: 'setting' },
  { id: 'sequences', label: 'Sequences', one: 'sequence' },
  { id: 'lists', label: 'Lists', one: 'list' },
]

function SectionBody({ projectId, tab }: { projectId: string; tab: Tab }) {
  const settings = useSection(projectId, SETTINGS)
  const sequences = useSection(projectId, SEQUENCES)
  const lists = useSection(projectId, LISTS)
  // all three hooks are mounted (and loaded) once; the tab only chooses what to show
  const cur = tab === 'settings' ? settings : tab === 'sequences' ? sequences : lists
  const st = cur.state
  const label = TABS.find((t) => t.id === tab)!

  const edit = <R,>(rows: R[], i: number, patch: Partial<R>, field: string) =>
    (cur.change as (r: R[], t?: [number, string]) => void)(rows.map((x, n) => (n === i ? { ...x, ...patch } : x)), [i, field])
  const remove = <R,>(rows: R[], i: number) => (cur.change as (r: R[]) => void)(rows.filter((_, n) => n !== i))

  if (st.status === 'loading') return <p className="empty-state">Loading {label.label.toLowerCase()}…</p>
  if (st.status === 'error') return <LoadFailed what={label.label.toLowerCase()} message={st.loadError} onRetry={cur.reload} />

  const msgs = msgsFor(st.issues, st.clientErrs)
  const add = () => {
    const rows = st.rows as unknown[]
    const fresh = tab === 'settings' ? blankSetting() : tab === 'sequences' ? blankSequence() : blankList()
    ;(cur.change as (r: unknown[]) => void)([...rows, fresh])
  }

  return (
    <div role="group" aria-label={label.label}>
      {st.conflict && <ConflictBanner onReload={cur.reload} />}
      <IssueSummary issues={st.issues} />
      {st.rows.length === 0 && (
        <div className="card empty-hero" data-testid={`${tab}-empty`}>
          <h2>No {label.label.toLowerCase()} yet</h2>
          <p>{INTRO[tab]}</p>
        </div>
      )}
      {tab === 'settings' && <SettingsEditor rows={settings.state.rows} msgs={msgs} issues={st.issues} onEdit={(i, p, f) => edit(settings.state.rows, i, p, f)} onRemove={(i) => remove(settings.state.rows, i)} />}
      {tab === 'sequences' && <SequencesEditor rows={sequences.state.rows} msgs={msgs} issues={st.issues} onEdit={(i, p, f) => edit(sequences.state.rows, i, p, f)} onRemove={(i) => remove(sequences.state.rows, i)} />}
      {tab === 'lists' && <ListsEditor rows={lists.state.rows} msgs={msgs} issues={st.issues} onEdit={(i, p, f) => edit(lists.state.rows, i, p, f)} onRemove={(i) => remove(lists.state.rows, i)} onRows={(r) => lists.change(r)} />}
      <div className="bh-actions">
        <button className="outline" onClick={add}>Add {label.one}</button>
      </div>
      <SaveBar dirty={st.dirty} saving={st.saving} onSave={cur.save} onDiscard={cur.reload} note={st.savedNote} error={st.saveError} />
    </div>
  )
}

export function SettingsPage({ projectId }: { projectId: string }) {
  const [tab, setTab] = useState<Tab>('settings')
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Settings</h1>
          <p>{INTRO[tab]}</p>
        </div>
      </div>
      <nav aria-label="Settings sections" className="bh-tabs">
        {TABS.map((t) => (
          <button key={t.id} className={t.id === tab ? '' : 'outline'} aria-pressed={t.id === tab} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>
      <SectionBody key={projectId} projectId={projectId} tab={tab} />
    </>
  )
}
