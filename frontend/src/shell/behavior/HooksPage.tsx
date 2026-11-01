import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { HookBody, HookFieldBody } from '../../api/types'
import {
  CEILINGS, ENTITY_TO_HOOK, FIXED_OUTPUT, GATE_COMMAND, HOOK_TYPES, blankHook, hookClientErrors, hookFromBody, hookIssues,
  hookToBody, legalKinds, legalPolicies, parsePoint, pointOptions, renameHook, retarget, setInputFromEntity,
  setOutputFromEntity, settableFields, signatureLine, stubPath, stubReady, stubText,
  type HookCatalog, type HookRow, type PointOption,
} from './hooksLogic'
import { useSection, type SectionConfig } from './useSection'
import { ConflictBanner, Field, IssueSummary, LoadFailed, SaveBar } from './ui'

const HOOKS: SectionConfig<HookRow, HookBody> = {
  key: 'hooks',
  load: async (id) => { const r = await api.getHooks(id); return { version: r.version, items: r.hooks } },
  save: async (id, items, v) => { const r = await api.putHooks(id, items, v); return { version: r.version, items: r.hooks } },
  fromBody: hookFromBody,
  toBody: hookToBody,
  check: hookClientErrors,
  mapIssues: hookIssues,
}

type CatalogLoad = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; catalog: HookCatalog }

async function loadCatalog(projectId: string): Promise<HookCatalog> {
  const entities = []
  for (let offset = 0; ; offset += 200) {
    const page = await api.listEntities(projectId, 200, offset)
    entities.push(...page.items)
    if (entities.length >= page.total || page.items.length === 0) break
  }
  const machines = await api.getStateMachines(projectId)
  const out: HookCatalog = {}
  await Promise.all(
    entities.map(async (e) => {
      const fields = await api.listFields(e.id, 200, 0)
      const machine = machines.state_machines.find((m) => m.entity === e.name)
      out[e.name] = {
        fields: [
          { name: 'id', type: 'uuid' },
          ...fields.items.flatMap((f) => (ENTITY_TO_HOOK[f.type] ? [{ name: f.name, type: ENTITY_TO_HOOK[f.type] }] : [])),
        ],
        stateField: machine?.field ?? null,
        transitions: (machine?.transitions ?? []).filter((t) => !t.auto).map((t) => t.name),
      }
    }),
  )
  return out
}

function downloadText(filename: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

const fieldList = (fields: HookFieldBody[] | undefined) =>
  fields?.length ? fields.map((f) => `${f.name}: ${f.type}${f.required === false ? '?' : ''}`).join(', ') : 'none'

function Summary({ r }: { r: HookRow }) {
  return (
    <dl className="bh-summary" data-testid="hook-summary">
      <dt>Point</dt><dd><code>{r.point}</code></dd>
      <dt>Kind</dt><dd>{r.kind}</dd>
      <dt>If it fails</dt><dd>{r.policy}</dd>
      <dt>Budget</dt><dd>{r.cpu_ms} ms CPU, {r.rows} rows, {r.outbound_calls} outbound calls</dd>
      <dt>Input {r.inputModel && <code>{r.inputModel}</code>}</dt><dd>{fieldList(r.inputFields)}</dd>
      <dt>Output {r.outputModel && <code>{r.outputModel}</code>}</dt><dd>{fieldList(r.outputFields)}</dd>
      {r.reads.length > 0 && (<><dt>May read</dt><dd>{r.reads.join(', ')}</dd></>)}
      {r.policy === 'fallback' && (
        <><dt>Fallback values</dt><dd>{Object.entries(r.fallback).map(([k, v]) => `${k} = ${v}`).join(', ') || 'none'}</dd></>
      )}
    </dl>
  )
}

function ContractBox({ r }: { r: HookRow }) {
  const ready = stubReady(r)
  const body = hookToBody(r)
  return (
    <div className="bh-contract" data-testid="hook-contract">
      <strong>Run the gate in your generated project</strong>
      <p className="muted">
        The platform does not run a gate for you here: the hook checks run inside the generated project. After you generate and
        unpack it, write the body of the stub and run:
      </p>
      <p><code data-testid="gate-command">{GATE_COMMAND}</code></p>
      {ready ? (
        <>
          <p>The generator creates <code data-testid="stub-path">{stubPath(body.name)}</code> with this fixed signature:</p>
          <p><code data-testid="stub-signature">{signatureLine(body.name, body.input.name, body.output.name)}</code></p>
          <details>
            <summary>Preview the whole stub</summary>
            <pre data-testid="stub-text" tabIndex={0}>{stubText(body)}</pre>
          </details>
          <button className="outline small" onClick={() => downloadText(`${body.name}.py`, stubText(body))}>
            Download stub
          </button>
        </>
      ) : (
        <p className="muted">Give the hook a name, a point and model names to see its stub.</p>
      )}
    </div>
  )
}

function PointSelect({ id, row, options, onPick, aria }: {
  id: string
  row: HookRow
  options: PointOption[]
  onPick: (v: string) => void
  aria?: Record<string, unknown>
}) {
  const groups = [...new Set(options.map((o) => o.group))]
  const known = options.some((o) => o.value === row.point)
  return (
    <select {...aria} id={id} value={row.point} onChange={(e) => onPick(e.target.value)}>
      {!known && <option value={row.point}>{row.point || 'Choose a point'} (not available)</option>}
      {groups.map((g) => (
        <optgroup key={g} label={g}>
          {options.filter((o) => o.group === g).map((o) => <option key={o.value} value={o.value}>{o.value.slice(g.length + 1)} — {o.label}</option>)}
        </optgroup>
      ))}
    </select>
  )
}

export function HooksPage({ projectId }: { projectId: string }) {
  const { state: st, change, save, reload } = useSection(projectId, HOOKS)
  const [cat, setCat] = useState<CatalogLoad>({ status: 'loading' })
  const [editing, setEditing] = useState<Set<number>>(new Set())

  const loadCat = useCallback(() => {
    setCat({ status: 'loading' })
    loadCatalog(projectId).then(
      (catalog) => setCat({ status: 'ready', catalog }),
      (err: unknown) => setCat({ status: 'error', message: err instanceof Error ? err.message : 'Could not load the entities' }),
    )
  }, [projectId])
  useEffect(loadCat, [loadCat])
  const retry = () => { reload(); loadCat(); setEditing(new Set()) }

  const header = (
    <div className="page-header">
      <div>
        <h1>Hooks</h1>
        <p>Hooks are small pieces of your own code that run at a fixed point of a record&apos;s life, such as before a transition. You declare their name, inputs, outputs and limits here; the platform checks that the code keeps to that contract.</p>
      </div>
    </div>
  )
  if (st.status === 'loading' || cat.status === 'loading') return <>{header}<p className="empty-state">Loading hooks…</p></>
  if (st.status === 'error') return <>{header}<LoadFailed what="hooks" message={st.loadError} onRetry={retry} /></>
  if (cat.status === 'error') return <>{header}<LoadFailed what="the entities" message={cat.message} onRetry={retry} /></>

  const catalog = cat.catalog
  const options = pointOptions(catalog)
  const msgs = (i: number, f: string) => [
    ...(st.clientErrs[`${i}.${f}`] ? [st.clientErrs[`${i}.${f}`]] : []),
    ...(st.issues.rows[i]?.fields[f] ?? []),
  ]
  const allMsgs = (i: number) => [...(st.issues.rows[i]?.row ?? []), ...Object.values(st.issues.rows[i]?.fields ?? {}).flat()]
  const replace = (i: number, next: HookRow, field?: string) =>
    change(st.rows.map((r, n) => (n === i ? next : r)), field ? [i, field] : undefined)
  const toggle = (k: number, on: boolean) => setEditing((p) => { const n = new Set(p); if (on) n.add(k); else n.delete(k); return n })

  return (
    <>
      {header}
      {st.conflict && <ConflictBanner onReload={retry} />}
      <IssueSummary issues={st.issues} />
      {st.rows.length === 0 && (
        <div className="card empty-hero" data-testid="hooks-empty">
          <h2>No hooks declared yet</h2>
          <p>A hook is where your own code plugs into the generated backend, for example to refuse an approval when an invoice does not match its purchase order. Declare one below to see the file the generator will create for it.</p>
        </div>
      )}
      {st.rows.map((r, i) => {
        const id = `hk-${r.k}`
        const parsed = parsePoint(r.point)
        const entity = parsed ? catalog[parsed.entity] : undefined
        const open = editing.has(r.k)
        const kinds = legalKinds(parsed?.stage ?? null)
        const policies = legalPolicies(parsed?.stage ?? null)
        const stage = parsed?.stage
        const ceiling = CEILINGS[r.kind as 'pure' | 'effect'] ?? CEILINGS.pure
        const budgetField = (key: 'cpu_ms' | 'rows' | 'outbound_calls', label: string, max: number) => (
          <Field id={`${id}-${key}`} label={label} hint={`0 to ${max}`} messages={msgs(i, key)}>
            {(p) => <input {...p} inputMode="numeric" value={r[key]} onChange={(e) => replace(i, { ...r, [key]: e.target.value }, key)} />}
          </Field>
        )
        return (
          <fieldset key={r.k} className="card bh-row bh-hook" data-testid="hook-row">
            <legend>{r.name || 'New hook'}</legend>
            {allMsgs(i).length > 0 && (
              <div role="alert" data-variant="danger" className="bh-alert" data-testid="hook-issues">
                <ul>{allMsgs(i).map((m, n) => <li key={n}>{m}</li>)}</ul>
              </div>
            )}
            {!open && <Summary r={r} />}
            {open && (
              <div data-testid="hook-form">
                <div className="bh-grid">
                  <Field id={`${id}-name`} label="Hook name" hint="lowercase letters, digits and _" messages={msgs(i, 'name')}>
                    {(p) => <input {...p} value={r.name} onChange={(e) => replace(i, renameHook(r, e.target.value), 'name')} />}
                  </Field>
                  <Field id={`${id}-point`} label="Where it runs" messages={msgs(i, 'point')}>
                    {(p) => <PointSelect id={p.id} aria={p} row={r} options={options} onPick={(v) => replace(i, retarget(r, v, catalog), 'point')} />}
                  </Field>
                  <Field id={`${id}-kind`} label="Kind" hint={kinds.length === 1 ? 'Only pure is possible at this point' : 'An effect runs after the commit'} messages={msgs(i, 'kind')}>
                    {(p) => (
                      <select {...p} value={r.kind} onChange={(e) => replace(i, retarget({ ...r, kind: e.target.value }, r.point, catalog), 'kind')}>
                        {kinds.map((k) => <option key={k}>{k}</option>)}
                      </select>
                    )}
                  </Field>
                  <Field id={`${id}-policy`} label="If the hook fails" hint={policies.length === 1 ? 'Guards and validation always refuse on failure' : undefined} messages={msgs(i, 'failure_policy')}>
                    {(p) => (
                      <select {...p} value={r.policy} onChange={(e) => replace(i, retarget({ ...r, policy: e.target.value }, r.point, catalog), 'failure_policy')}>
                        {policies.map((k) => <option key={k}>{k}</option>)}
                      </select>
                    )}
                  </Field>
                </div>
                <div className="bh-grid">
                  {budgetField('cpu_ms', 'CPU budget (ms)', ceiling.cpu_ms)}
                  {budgetField('rows', 'Rows it may read', ceiling.rows)}
                  {budgetField('outbound_calls', 'Outbound calls', ceiling.outbound_calls)}
                </div>
                {r.kind === 'effect' && (
                  <div className="bh-checks" role="group" aria-label="Entities the hook may read">
                    {Object.keys(catalog).sort().map((n) => (
                      <div key={n} className="bh-check">
                        <input id={`${id}-reads-${n}`} type="checkbox" checked={r.reads.includes(n)}
                          onChange={(e) => replace(i, { ...r, reads: e.target.checked ? [...r.reads, n] : r.reads.filter((x) => x !== n) }, 'reads')} />
                        <label htmlFor={`${id}-reads-${n}`}>may read {n}</label>
                      </div>
                    ))}
                    {msgs(i, 'reads').length > 0 && <small className="bh-error" data-testid="field-error">{msgs(i, 'reads').join(' ')}</small>}
                  </div>
                )}
                <div className="bh-grid">
                  <Field id={`${id}-in`} label="Input model name" messages={msgs(i, 'inputModel')}>
                    {(p) => <input {...p} value={r.inputModel} onChange={(e) => replace(i, { ...r, inputModel: e.target.value }, 'inputModel')} />}
                  </Field>
                  <Field id={`${id}-out`} label="Output model name" messages={msgs(i, 'outputModel')}>
                    {(p) => <input {...p} value={r.outputModel} onChange={(e) => replace(i, { ...r, outputModel: e.target.value }, 'outputModel')} />}
                  </Field>
                </div>
                <div className="bh-checks" role="group" aria-label="Input fields the hook receives">
                  {[...(entity?.fields ?? []), ...r.inputFields.filter((f) => !entity?.fields.some((x) => x.name === f.name))].map((f) => (
                    <div key={f.name} className="bh-check">
                      <input id={`${id}-if-${f.name}`} type="checkbox" checked={r.inputFields.some((x) => x.name === f.name)}
                        onChange={(e) => replace(i, setInputFromEntity(r, entity, f.name, e.target.checked), 'inputFields')} />
                      <label htmlFor={`${id}-if-${f.name}`}>{f.name} <small className="muted">{f.type}</small></label>
                    </div>
                  ))}
                  {msgs(i, 'inputFields').length > 0 && <small className="bh-error" data-testid="field-error">{msgs(i, 'inputFields').join(' ')}</small>}
                </div>
                {(stage === 'validate' || stage === 'transition_guard') && (
                  <p className="muted">Output (fixed for this point): {fieldList(FIXED_OUTPUT[stage])}.</p>
                )}
                {stage === 'before_save' && (
                  <div className="bh-checks" role="group" aria-label="Fields the hook sets">
                    {settableFields(entity).map((f) => (
                      <div key={f.name} className="bh-check">
                        <input id={`${id}-of-${f.name}`} type="checkbox" checked={r.outputFields.some((x) => x.name === f.name)}
                          onChange={(e) => replace(i, setOutputFromEntity(r, entity, f.name, e.target.checked), 'outputFields')} />
                        <label htmlFor={`${id}-of-${f.name}`}>sets {f.name} <small className="muted">{f.type}</small></label>
                      </div>
                    ))}
                  </div>
                )}
                {(stage === 'after_save' || stage === 'after_commit') && (
                  <div data-testid="output-fields">
                    {r.outputFields.map((f, n) => (
                      <div key={n} className="bh-grid">
                        <Field id={`${id}-of-${n}`} label={`Output field ${n + 1} name`}>
                          {(p) => <input {...p} value={f.name} onChange={(e) => replace(i, { ...r, outputFields: r.outputFields.map((x, m) => (m === n ? { ...x, name: e.target.value } : x)) }, 'outputFields')} />}
                        </Field>
                        <Field id={`${id}-ot-${n}`} label={`Output field ${n + 1} type`}>
                          {(p) => (
                            <select {...p} value={f.type} onChange={(e) => replace(i, { ...r, outputFields: r.outputFields.map((x, m) => (m === n ? { ...x, type: e.target.value } : x)) }, 'outputFields')}>
                              {HOOK_TYPES.map((t) => <option key={t}>{t}</option>)}
                            </select>
                          )}
                        </Field>
                        <button className="outline small" aria-label={`Remove output field ${n + 1}`} onClick={() => replace(i, { ...r, outputFields: r.outputFields.filter((_, m) => m !== n) }, 'outputFields')}>Remove field</button>
                      </div>
                    ))}
                    <button className="outline small" onClick={() => replace(i, { ...r, outputFields: [...r.outputFields, { name: '', type: 'string', required: true }] }, 'outputFields')}>Add output field</button>
                  </div>
                )}
                {msgs(i, 'outputFields').length > 0 && <small className="bh-error" data-testid="field-error">{msgs(i, 'outputFields').join(' ')}</small>}
                {r.policy === 'fallback' && (
                  <div className="bh-grid" data-testid="fallback-values">
                    {r.outputFields.map((f) => (
                      <Field key={f.name} id={`${id}-fb-${f.name}`} label={`Fallback value for ${f.name}`} hint={f.type} messages={f.name === r.outputFields[0]?.name ? msgs(i, 'fallback') : undefined}>
                        {(p) => <input {...p} value={r.fallback[f.name] ?? ''} onChange={(e) => replace(i, { ...r, fallback: { ...r.fallback, [f.name]: e.target.value } }, 'fallback')} />}
                      </Field>
                    ))}
                  </div>
                )}
              </div>
            )}
            <ContractBox r={r} />
            <div className="bh-actions">
              <button className="outline small" onClick={() => toggle(r.k, !open)} aria-expanded={open}>{open ? 'Done editing' : 'Edit'}</button>
              <button className="outline small" aria-label={`Remove hook ${r.name || 'New hook'}`} onClick={() => { toggle(r.k, false); change(st.rows.filter((_, n) => n !== i)) }}>Remove</button>
            </div>
          </fieldset>
        )
      })}
      <div className="bh-actions">
        {options.length > 0 ? (
          <button className="outline" onClick={() => { const row = blankHook(catalog); toggle(row.k, true); change([...st.rows, row]) }}>Declare a hook</button>
        ) : (
          <small className="muted">Add an entity in the data model first: a hook belongs to a point of an entity.</small>
        )}
      </div>
      <SaveBar dirty={st.dirty} saving={st.saving} onSave={save} onDiscard={() => { reload(); setEditing(new Set()) }} note={st.savedNote} error={st.saveError} />
    </>
  )
}
