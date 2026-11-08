import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api/client'
import type { SeedProfileBody } from '../../api/types'
import {
  GENERATORS, GUARD_NOTE, asOfYear, blankEntityPlan, blankFieldPlan, blankProfile, columnTypes, generatorsFor, isProfileName,
  missingRequired, plannableColumns, profileFromBody, profileToBody, reachableStates, retypeGen, runCommands, seedClientErrors,
  seedIssues, suggestGen, targetOf, withStateWeights,
  type ColumnTypes, type EntityPlanRow, type GenRow, type ProfileRow, type SeedCatalog, type Target,
} from './seedLogic'
import { useSection, type SectionConfig } from './useSection'
import { ConflictBanner, Field, IssueSummary, LoadFailed, SaveBar } from './ui'

type CatalogLoad = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; catalog: SeedCatalog }

async function loadAll<T>(page: (offset: number) => Promise<{ items: T[]; total: number }>): Promise<T[]> {
  const out: T[] = []
  for (let offset = 0; ; offset += 200) {
    const p = await page(offset)
    out.push(...p.items)
    if (out.length >= p.total || p.items.length === 0) return out
  }
}

async function loadCatalog(projectId: string): Promise<SeedCatalog> {
  const entities = await loadAll((o) => api.listEntities(projectId, 200, o))
  const relations = await loadAll((o) => api.listRelations(projectId, 200, o))
  const machines = (await api.getStateMachines(projectId)).state_machines
  const nameOf = new Map(entities.map((e) => [e.id, e.name]))
  const out: SeedCatalog = {}
  await Promise.all(
    entities.map(async (e) => {
      const fields = await loadAll((o) => api.listFields(e.id, 200, o))
      const machine = machines.find((m) => m.entity === e.name)
      const stateCol = machine ? fields.find((f) => f.name === machine.field) : undefined
      out[e.name] = {
        columns: fields.map((f) => ({
          name: f.name, type: f.type, required: f.required, unique: f.unique, hasDefault: f.default !== null && f.default !== undefined,
          maxLength: f.max_length, minValue: f.min_value, maxValue: f.max_value, enumValues: f.enum_values ?? [],
        })),
        fks: relations
          .filter((r) => (r.kind === 'one_to_many' || r.kind === 'one_to_one') && r.to_entity_id === e.id)
          .map((r) => ({ column: `${r.to_name}_id`, target: nameOf.get(r.from_entity_id) ?? '', required: r.required, unique: r.kind === 'one_to_one' })),
        stateField: machine?.field ?? null,
        reachable: reachableStates(machine, stateCol?.enum_values ?? []),
      }
    }),
  )
  return out
}

const planSummary = (e: EntityPlanRow) => `${e.entity}: ${e.count} ${e.count === '1' ? 'row' : 'rows'}, ${e.fields.length} ${e.fields.length === 1 ? 'field' : 'fields'} planned`

function Summary({ p }: { p: ProfileRow }) {
  return (
    <dl className="bh-summary" data-testid="seed-summary">
      <dt>Seed number</dt><dd>{p.seed}</dd>
      <dt>As of</dt><dd>{p.as_of}</dd>
      <dt>Tenants</dt><dd>{p.tenants}</dd>
      <dt>Plans</dt><dd>{p.entities.length ? <ul>{p.entities.map((e) => <li key={e.k}>{planSummary(e)}</li>)}</ul> : 'none yet'}</dd>
    </dl>
  )
}

function RunBox({ name }: { name: string }) {
  const ok = isProfileName(name)
  const c = runCommands(ok ? name : 'NAME')
  return (
    <div className="bh-contract" data-testid="seed-run">
      <strong>How to run it</strong>
      <p className="muted">Seed data is created from your generated project, not from this page. After you generate and unpack it:</p>
      <ul>
        <li>Create the data: <code data-testid="cmd-seed">{c.seed}</code></li>
        <li>Delete what this profile created and create it again: <code data-testid="cmd-reset">{c.reset}</code></li>
        <li>Check the seeded rows: <code data-testid="cmd-check">{c.check}</code></li>
      </ul>
      <p className="muted" data-testid="seed-guard-note">{GUARD_NOTE}</p>
    </div>
  )
}

export function SeedPage({ projectId }: { projectId: string }) {
  const typesRef = useRef<ColumnTypes>({})
  const cfg: SectionConfig<ProfileRow, SeedProfileBody> = {
    key: 'seed',
    load: async (id) => { const r = await api.getSeed(id); return { version: r.version, items: r.seed } },
    save: async (id, items, v) => { const r = await api.putSeed(id, items, v); return { version: r.version, items: r.seed } },
    fromBody: (b) => profileFromBody(b),
    toBody: (r) => profileToBody(r, typesRef.current),
    check: seedClientErrors,
    mapIssues: seedIssues,
  }
  const { state: st, change, save, reload } = useSection(projectId, cfg)
  const [cat, setCat] = useState<CatalogLoad>({ status: 'loading' })
  const [editing, setEditing] = useState<Set<number>>(new Set())

  const loadCat = useCallback(() => {
    setCat({ status: 'loading' })
    loadCatalog(projectId).then(
      (catalog) => { typesRef.current = columnTypes(catalog); setCat({ status: 'ready', catalog }) },
      (err: unknown) => setCat({ status: 'error', message: err instanceof Error ? err.message : 'Could not load the entities' }),
    )
  }, [projectId])
  useEffect(loadCat, [loadCat])
  const retry = () => { reload(); loadCat(); setEditing(new Set()) }

  const header = (
    <div className="page-header">
      <div>
        <h1>Seed data</h1>
        <p>Seed data is a set of made-up but realistic rows that your generated project can create for demos and development. A seed profile is a named, repeatable recipe: the same profile always produces the same rows. Nothing here touches a real database.</p>
      </div>
    </div>
  )
  if (st.status === 'loading' || cat.status === 'loading') return <>{header}<p className="empty-state">Loading seed data…</p></>
  if (st.status === 'error') return <>{header}<LoadFailed what="seed profiles" message={st.loadError} onRetry={retry} /></>
  if (cat.status === 'error') return <>{header}<LoadFailed what="the entities" message={cat.message} onRetry={retry} /></>

  const catalog = cat.catalog
  const entityNames = Object.keys(catalog).sort()
  const msgs = (i: number, key: string) => [
    ...(st.clientErrs[`${i}.${key}`] ? [st.clientErrs[`${i}.${key}`]] : []),
    ...(st.issues.rows[i]?.fields[key] ?? []),
  ]
  const allMsgs = (i: number) => [...(st.issues.rows[i]?.row ?? []), ...Object.values(st.issues.rows[i]?.fields ?? {}).flat()]
  const setProfile = (i: number, fn: (p: ProfileRow) => ProfileRow, key?: string) =>
    change(st.rows.map((r, n) => (n === i ? fn(r) : r)), key ? [i, key] : undefined)
  const setPlan = (i: number, j: number, fn: (e: EntityPlanRow) => EntityPlanRow, key?: string) =>
    setProfile(i, (p) => ({ ...p, entities: p.entities.map((e, n) => (n === j ? fn(e) : e)) }), key)
  const setGen = (i: number, j: number, k: number, fn: (g: GenRow) => GenRow, key?: string) =>
    setPlan(i, j, (e) => ({ ...e, fields: e.fields.map((f, n) => (n === k ? { ...f, gen: fn(f.gen) } : f)) }), key)
  const toggle = (k: number, on: boolean) => setEditing((p) => { const n = new Set(p); if (on) n.add(k); else n.delete(k); return n })

  const genControls = (i: number, j: number, k: number, g: GenRow, t: Target, id: string) => {
    const gk = (part: string) => `entities.${j}.fields.${k}.generator.${part}`
    const set = (patch: Partial<GenRow>, part: string) => setGen(i, j, k, (x) => ({ ...x, ...patch }), gk(part))
    const text = (part: 'prefix' | 'start' | 'width' | 'min' | 'max' | 'places' | 'ratio' | 'min_words' | 'max_words', label: string, hint?: string) => (
      <Field id={`${id}-${part}`} label={label} hint={hint} messages={msgs(i, gk(part))}>
        {(p) => <input {...p} value={g[part]} onChange={(e) => set({ [part]: e.target.value }, part)} />}
      </Field>
    )
    const isInt = t.kind === 'field' && ['integer', 'bigint'].includes(t.col.type)
    switch (g.type) {
      case 'constant':
        return (
          <Field id={`${id}-value`} label="Value" messages={msgs(i, gk('value'))}>
            {(p) => t.kind === 'field' && t.col.type === 'enum' ? (
              <select {...p} value={g.value} onChange={(e) => set({ value: e.target.value }, 'value')}>
                {t.col.enumValues.map((v) => <option key={v}>{v}</option>)}
              </select>
            ) : t.kind === 'field' && t.col.type === 'boolean' ? (
              <select {...p} value={g.value} onChange={(e) => set({ value: e.target.value }, 'value')}><option>true</option><option>false</option></select>
            ) : <input {...p} value={g.value} onChange={(e) => set({ value: e.target.value }, 'value')} />}
          </Field>
        )
      case 'one_of':
        if (t.kind === 'field' && t.col.type === 'enum') {
          const chosen = g.values.split('\n').filter(Boolean)
          return (
            <div className="bh-checks" role="group" aria-label="Values to pick from">
              {t.col.enumValues.map((v) => (
                <div key={v} className="bh-check">
                  <input id={`${id}-v-${v}`} type="checkbox" checked={chosen.includes(v)}
                    onChange={(e) => set({ values: t.col.enumValues.filter((x) => (x === v ? e.target.checked : chosen.includes(x))).join('\n') }, 'values')} />
                  <label htmlFor={`${id}-v-${v}`}>{v}</label>
                </div>
              ))}
              {msgs(i, gk('values')).length > 0 && <small className="bh-error" data-testid="field-error">{msgs(i, gk('values')).join(' ')}</small>}
            </div>
          )
        }
        return (
          <Field id={`${id}-values`} label="Values (one per line)" messages={msgs(i, gk('values'))}>
            {(p) => <textarea {...p} rows={3} value={g.values} onChange={(e) => set({ values: e.target.value }, 'values')} />}
          </Field>
        )
      case 'sequence':
        return (
          <div className="bh-grid">
            {!isInt && text('prefix', 'Prefix', 'letters, digits and _ . -')}
            {text('start', 'Start at')}
            {!isInt && text('width', 'Zero padding (digits)')}
          </div>
        )
      case 'int_range': return <div className="bh-grid">{text('min', 'Minimum')}{text('max', 'Maximum')}</div>
      case 'decimal_range': return <div className="bh-grid">{text('min', 'Minimum', 'as text, like 10.50')}{text('max', 'Maximum')}{text('places', 'Decimal places')}</div>
      case 'date_range': return <div className="bh-grid">{text('min', 'Earliest date', 'YYYY-MM-DD')}{text('max', 'Latest date', 'YYYY-MM-DD')}</div>
      case 'bool_ratio': return text('ratio', 'Share of true values', '0 to 1')
      case 'words': return <div className="bh-grid">{text('min_words', 'Fewest words')}{text('max_words', 'Most words')}</div>
      case 'email': return text('prefix', 'Address prefix', 'lowercase letters and digits')
      case 'reference': {
        const unique = t.kind === 'fk' && t.fk.unique
        return (
          <div className="bh-grid">
            <Field id={`${id}-entity`} label="Points at" messages={msgs(i, gk('entity'))}>
              {(p) => <select {...p} value={g.entity} onChange={(e) => set({ entity: e.target.value }, 'entity')}>{t.kind === 'fk' && <option>{t.fk.target}</option>}</select>}
            </Field>
            <Field id={`${id}-pick`} label="How rows are chosen" hint={unique ? 'one-to-one: every row needs its own, so cycle' : undefined} messages={msgs(i, gk('pick'))}>
              {(p) => <select {...p} value={g.pick || 'cycle'} onChange={(e) => set({ pick: e.target.value }, 'pick')}>{(unique ? ['cycle'] : ['cycle', 'random']).map((v) => <option key={v}>{v}</option>)}</select>}
            </Field>
          </div>
        )
      }
      default: return null
    }
  }

  const planBlock = (i: number, p: ProfileRow, j: number, e: EntityPlanRow) => {
    const info = catalog[e.entity]
    const pid = `sd-${p.k}-${e.k}`
    const free = entityNames.filter((n) => n === e.entity || !p.entities.some((x) => x.entity === n))
    const addable = plannableColumns(info, e)
    const missing = missingRequired(info, e)
    const year = asOfYear(p.as_of)
    const addFields = (names: string[]) => setPlan(i, j, (x) => ({
      ...x,
      fields: [...x.fields, ...names.flatMap((n) => {
        const t = targetOf(info, n)
        return t ? [blankFieldPlan(n, withStateWeights(suggestGen(t, { asOfYear: year }), info, info?.reachable ?? []))] : []
      })],
    }))
    return (
      <div key={e.k} className="bh-plan" role="group" aria-label={`Plan for ${e.entity || 'an entity'}`} data-testid="plan-row">
        <div className="bh-grid">
          <Field id={`${pid}-entity`} label="Entity" messages={msgs(i, `entities.${j}.entity`)}>
            {(q) => (
              <select {...q} value={e.entity} onChange={(ev) => setPlan(i, j, (x) => ({ ...x, entity: ev.target.value, fields: [] }), `entities.${j}.entity`)}>
                {free.map((n) => <option key={n}>{n}</option>)}
              </select>
            )}
          </Field>
          <Field id={`${pid}-count`} label="Rows" hint="per tenant when the entity belongs to a tenant" messages={msgs(i, `entities.${j}.count`)}>
            {(q) => <input {...q} inputMode="numeric" value={e.count} onChange={(ev) => setPlan(i, j, (x) => ({ ...x, count: ev.target.value }), `entities.${j}.count`)} />}
          </Field>
        </div>
        {msgs(i, `entities.${j}.fields`).length > 0 && <div role="alert" data-variant="danger" className="bh-alert" data-testid="plan-issues">{msgs(i, `entities.${j}.fields`).join(' ')}</div>}
        {e.fields.map((f, k) => {
          const t = targetOf(info, f.field)
          const fid = `${pid}-${f.k}`
          const options = t ? generatorsFor(t) : []
          const states = t && t.kind === 'field' && t.isState ? [...new Set([...(info?.reachable ?? []), ...Object.keys(f.gen.weights)])] : []
          return (
            <div key={f.k} className="bh-genrow" role="group" aria-label={`${e.entity}.${f.field}`} data-testid="field-plan">
              <div className="bh-grid">
                <div className="bh-field">
                  <strong>{f.field}</strong> <small className="muted">{t ? (t.kind === 'fk' ? 'foreign key' : t.isState ? `${t.col.type}, state` : `${t.col.type}${t.col.unique ? ', unique' : ''}`) : 'not found'}</small>
                  {msgs(i, `entities.${j}.fields.${k}.field`).length > 0 && <small className="bh-error" data-testid="field-error">{msgs(i, `entities.${j}.fields.${k}.field`).join(' ')}</small>}
                </div>
                <Field id={`${fid}-type`} label="Generator" hint={GENERATORS[f.gen.type]?.hint} messages={msgs(i, `entities.${j}.fields.${k}.generator.type`)}>
                  {(q) => (
                    <select {...q} value={f.gen.type}
                      onChange={(ev) => t && setGen(i, j, k, () => withStateWeights(retypeGen(t, ev.target.value, { asOfYear: year }), info, info?.reachable ?? []), `entities.${j}.fields.${k}.generator.type`)}>
                      {!options.includes(f.gen.type) && <option value={f.gen.type}>{f.gen.type} (not possible here)</option>}
                      {options.map((o) => <option key={o} value={o}>{o}</option>)}
                    </select>
                  )}
                </Field>
              </div>
              {t && genControls(i, j, k, f.gen, t, fid)}
              {states.length > 0 && (
                <div className="bh-grid" data-testid="state-weights">
                  {states.map((s) => (
                    <Field key={s} id={`${fid}-w-${s}`} label={`Weight of ${s}`} hint="0 to 1000" messages={msgs(i, `entities.${j}.fields.${k}.generator.weights.${s}`)}>
                      {(q) => <input {...q} inputMode="numeric" value={f.gen.weights[s] ?? ''} onChange={(ev) => setGen(i, j, k, (g) => ({ ...g, weights: { ...g.weights, [s]: ev.target.value } }), `entities.${j}.fields.${k}.generator.weights.${s}`)} />}
                    </Field>
                  ))}
                  {msgs(i, `entities.${j}.fields.${k}.generator.weights`).length > 0 && <small className="bh-error" data-testid="field-error">{msgs(i, `entities.${j}.fields.${k}.generator.weights`).join(' ')}</small>}
                </div>
              )}
              {msgs(i, `entities.${j}.fields.${k}.generator`).length > 0 && <small className="bh-error" data-testid="field-error">{msgs(i, `entities.${j}.fields.${k}.generator`).join(' ')}</small>}
              <button className="outline small" aria-label={`Remove field plan ${e.entity}.${f.field}`}
                onClick={() => setPlan(i, j, (x) => ({ ...x, fields: x.fields.filter((_, n) => n !== k) }))}>Remove field</button>
            </div>
          )
        })}
        <div className="bh-actions">
          {missing.length > 0 && (
            <button className="outline small" onClick={() => addFields(missing)}>Add the {missing.length} required {missing.length === 1 ? 'field' : 'fields'} ({missing.join(', ')})</button>
          )}
          {addable.length > 0 && (
            <select aria-label={`Add a field to fill in ${e.entity}`} value="" onChange={(ev) => ev.target.value && addFields([ev.target.value])}>
              <option value="">Add a field to fill…</option>
              {addable.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          )}
          <button className="outline small" aria-label={`Remove plan ${e.entity}`} onClick={() => setProfile(i, (x) => ({ ...x, entities: x.entities.filter((_, n) => n !== j) }))}>Remove plan</button>
        </div>
      </div>
    )
  }

  return (
    <>
      {header}
      {st.conflict && <ConflictBanner onReload={retry} />}
      <IssueSummary issues={st.issues} />
      {st.rows.length === 0 && (
        <div className="card empty-hero" data-testid="seed-empty">
          <h2>No seed profiles yet</h2>
          <p>Seed data is made-up sample rows, such as ten customers and fifty invoices, that fill a fresh copy of your app so you can try it. Add a profile below and choose how many rows each entity gets.</p>
        </div>
      )}
      {st.rows.map((p, i) => {
        const open = editing.has(p.k)
        const id = `sd-${p.k}`
        const unused = entityNames.filter((n) => !p.entities.some((x) => x.entity === n))
        return (
          <fieldset key={p.k} className="card bh-row bh-hook" data-testid="seed-row">
            <legend>{p.name || 'New profile'}</legend>
            {allMsgs(i).length > 0 && (
              <div role="alert" data-variant="danger" className="bh-alert" data-testid="seed-issues">
                <ul>{allMsgs(i).map((m, n) => <li key={n}>{m}</li>)}</ul>
              </div>
            )}
            {!open && <Summary p={p} />}
            {open && (
              <div data-testid="seed-form">
                <div className="bh-grid">
                  <Field id={`${id}-name`} label="Profile name" hint="lowercase letters, digits and _" messages={msgs(i, 'name')}>
                    {(q) => <input {...q} value={p.name} onChange={(e) => setProfile(i, (x) => ({ ...x, name: e.target.value }), 'name')} />}
                  </Field>
                  <Field id={`${id}-seed`} label="Seed number" hint="the same number always gives the same rows" messages={msgs(i, 'seed')}>
                    {(q) => <input {...q} inputMode="numeric" value={p.seed} onChange={(e) => setProfile(i, (x) => ({ ...x, seed: e.target.value }), 'seed')} />}
                  </Field>
                  <Field id={`${id}-asof`} label="As of date" hint="YYYY-MM-DD, the clock for the first row" messages={msgs(i, 'as_of')}>
                    {(q) => <input {...q} value={p.as_of} onChange={(e) => setProfile(i, (x) => ({ ...x, as_of: e.target.value }), 'as_of')} />}
                  </Field>
                  <Field id={`${id}-tenants`} label="Tenants" hint="0 unless the project is multi-tenant" messages={msgs(i, 'tenants')}>
                    {(q) => <input {...q} inputMode="numeric" value={p.tenants} onChange={(e) => setProfile(i, (x) => ({ ...x, tenants: e.target.value }), 'tenants')} />}
                  </Field>
                </div>
                {p.entities.map((e, j) => planBlock(i, p, j, e))}
                {msgs(i, 'entities').length > 0 && <small className="bh-error" data-testid="field-error">{msgs(i, 'entities').join(' ')}</small>}
                {unused.length > 0 ? (
                  <select aria-label={`Add an entity plan to ${p.name || 'this profile'}`} value="" onChange={(e) => e.target.value && setProfile(i, (x) => ({ ...x, entities: [...x.entities, blankEntityPlan(e.target.value)] }))}>
                    <option value="">Add an entity to seed…</option>
                    {unused.map((n) => <option key={n} value={n}>{n}</option>)}
                  </select>
                ) : entityNames.length === 0 ? <small className="muted">Add an entity in the data model first: a plan fills one entity.</small> : null}
              </div>
            )}
            <RunBox name={p.name} />
            <div className="bh-actions">
              <button className="outline small" onClick={() => toggle(p.k, !open)} aria-expanded={open}>{open ? 'Done editing' : 'Edit'}</button>
              <button className="outline small" aria-label={`Remove profile ${p.name || 'New profile'}`} onClick={() => { toggle(p.k, false); change(st.rows.filter((_, n) => n !== i)) }}>Remove</button>
            </div>
          </fieldset>
        )
      })}
      <div className="bh-actions">
        <button className="outline" disabled={st.rows.length >= 5} onClick={() => { const row = blankProfile(st.rows.map((r) => r.name)); toggle(row.k, true); change([...st.rows, row]) }}>Add a profile</button>
        {st.rows.length >= 5 && <small className="muted">A project can have at most 5 seed profiles.</small>}
      </div>
      <SaveBar dirty={st.dirty} saving={st.saving} onSave={save} onDiscard={() => { reload(); setEditing(new Set()) }} note={st.savedNote} error={st.saveError} />
    </>
  )
}
