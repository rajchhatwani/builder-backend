import { useId, useState } from 'react'
import { formatPoint } from '../map/mapLogic'
import {
  EMPTY_FENCE, addVertex, fenceBody, fenceDraft, llComplete, moveVertex, removeVertex, setVertex, toPt, type FenceDraft, type Geofence, type LL,
} from './opsLogic'
import { Confirm, DegInput, Feedback, PointInput, State, WholeInput, isPage, must, useAction, useGet, type Call, type Page } from './opsShared'

type Fence = Geofence & { created_at?: string }
const describe = (g: Fence) => (g.shape === 'circle' && g.center ? `centre ${formatPoint(g.center)}, radius ${g.radius_m} m` : `${g.vertices?.length ?? 0} vertices`)

/** The polygon vertices editor: add, remove, reorder, and type each vertex in decimal degrees. */
export function VerticesEditor({ vertices, onChange }: { vertices: LL[]; onChange: (v: LL[]) => void }) {
  const id = useId()
  return (
    <fieldset className="stack" data-testid="vertices-editor">
      <legend>Polygon vertices (in order, at least 3)</legend>
      {vertices.map((v, i) => (
        // eslint-disable-next-line react/no-array-index-key
        <div className="hstack" key={i} data-testid="vertex-row">
          <DegInput id={`${id}-${i}-lat`} label={`Vertex ${i + 1} latitude`} value={v.lat} limit={90} testid="vertex-lat" onChange={(lat) => onChange(setVertex(vertices, i, { ...v, lat }))} />
          <DegInput id={`${id}-${i}-lng`} label={`Vertex ${i + 1} longitude`} value={v.lng} limit={180} testid="vertex-lng" onChange={(lng) => onChange(setVertex(vertices, i, { ...v, lng }))} />
          <button type="button" className="outline" aria-label={`Move vertex ${i + 1} up`} disabled={i === 0} onClick={() => onChange(moveVertex(vertices, i, -1))}>Up</button>
          <button type="button" className="outline" aria-label={`Move vertex ${i + 1} down`} disabled={i === vertices.length - 1} onClick={() => onChange(moveVertex(vertices, i, 1))}>Down</button>
          <button type="button" className="outline" aria-label={`Remove vertex ${i + 1}`} data-testid="vertex-remove" onClick={() => onChange(removeVertex(vertices, i))}>Remove</button>
        </div>
      ))}
      <div><button type="button" className="outline" data-testid="vertex-add" onClick={() => onChange(addVertex(vertices))}>Add vertex</button></div>
    </fieldset>
  )
}

export function FencesPanel({ call, onChanged }: { call: Call; onChanged: () => void }) {
  const id = useId()
  const [list, reload] = useGet<Page<Fence>>(call, '/geo/geofences?limit=100&offset=0', 'geo')
  const [draft, setDraft] = useState<FenceDraft>(EMPTY_FENCE)
  const [confirm, setConfirm] = useState<Fence | null>(null)
  const save = useAction()
  const del = useAction()
  const contains = useAction()
  const [point, setPoint] = useState<LL>({ lat: null, lng: null })
  const [inside, setInside] = useState<string[] | null>(null)
  const editing = draft.id !== null

  async function submit() {
    const b = fenceBody(draft)
    if (!b.ok) { save.fail(b.error); return }
    await save.run(async () => {
      await must(call, editing ? 'PUT' : 'POST', editing ? `/geo/geofences/${draft.id}` : '/geo/geofences', b.body, 'geo')
      setDraft(EMPTY_FENCE); reload(); onChanged()
      return editing ? 'Geofence updated.' : 'Geofence created.'
    })
  }
  async function remove(g: Fence) {
    if (await del.run(async () => { await must(call, 'DELETE', `/geo/geofences/${g.id}`, undefined, 'geo'); return `Deleted ${g.name}.` })) {
      setConfirm(null); if (draft.id === g.id) setDraft(EMPTY_FENCE); reload(); onChanged()
    } else setConfirm(null)
  }
  async function check() {
    const p = toPt(point)
    if (!p) { contains.fail('Enter a latitude and a longitude to check.'); return }
    setInside(null)
    await contains.run(async () => {
      const j = (await must(call, 'POST', '/geo/contains', { point: p }, 'geo')) as { items?: { name: string }[] }
      setInside((j.items ?? []).map((g) => g.name))
    })
  }

  return (
    <div className="stack" data-testid="fences-panel">
      <h2>Geofences</h2>
      <State l={list} id="fences" empty={(v) => !isPage(v) || v.items.length === 0} emptyText="No geofences yet. Create one below.">
        {(v) => (
          <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Geofences">
            <table className="stage-table" data-testid="fence-table">
              <caption className="sr-only">Geofences</caption>
              <thead><tr><th scope="col">Name</th><th scope="col">Shape</th><th scope="col">Extent</th><th scope="col">Actions</th></tr></thead>
              <tbody>{v.items.map((g) => (
                <tr key={g.id} data-testid="fence-row">
                  <th scope="row">{g.name}</th><td>{g.shape}</td><td>{describe(g)}</td>
                  <td className="hstack">
                    <button type="button" className="outline" aria-label={`Edit ${g.name}`} data-testid="fence-edit" onClick={() => { setDraft(fenceDraft(g)); save.clear() }}>Edit</button>
                    <button type="button" className="outline" aria-label={`Delete ${g.name}`} data-testid="fence-delete" disabled={del.busy} onClick={() => setConfirm(g)}>Delete</button>
                  </td>
                </tr>))}
              </tbody>
            </table>
          </div>
        )}
      </State>
      {confirm && <Confirm testid="fence-confirm" busy={del.busy} yes="Yes, delete geofence" text={`Delete the geofence ${confirm.name}? Its past enter and exit events stay in the log.`} onYes={() => void remove(confirm)} onNo={() => setConfirm(null)} />}
      <Feedback a={del} id="fence-del" />

      <form className="stack" aria-labelledby={`${id}-h`} data-testid="fence-form" onSubmit={(e) => { e.preventDefault(); void submit() }}>
        <h3 id={`${id}-h`}>{editing ? 'Edit geofence' : 'Add a geofence'}</h3>
        <div className="hstack">
          <label htmlFor={`${id}-name`}>Name</label>
          <input id={`${id}-name`} value={draft.name} maxLength={200} data-testid="fence-name" onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          <label htmlFor={`${id}-shape`}>Shape</label>
          <select id={`${id}-shape`} value={draft.shape} data-testid="fence-shape" onChange={(e) => setDraft({ ...draft, shape: e.target.value as 'circle' | 'polygon' })}>
            <option value="circle">Circle</option><option value="polygon">Polygon</option>
          </select>
        </div>
        {draft.shape === 'circle' ? (
          <div className="stack">
            <PointInput legend="Centre" testid="fence-center" value={draft.center} onChange={(center) => setDraft({ ...draft, center })} />
            <div className="hstack"><WholeInput id={`${id}-r`} label="Radius (metres)" value={draft.radius} min={1} max={20_000_000} testid="fence-radius" onChange={(radius) => setDraft({ ...draft, radius })} /></div>
          </div>
        ) : <VerticesEditor vertices={draft.vertices} onChange={(vertices) => setDraft({ ...draft, vertices })} />}
        <div className="hstack">
          <button type="submit" disabled={save.busy} data-testid="fence-save">{save.busy ? 'Saving…' : editing ? 'Save geofence' : 'Create geofence'}</button>
          {editing && <button type="button" className="outline" onClick={() => { setDraft(EMPTY_FENCE); save.clear() }}>Cancel edit</button>}
        </div>
        <Feedback a={save} id="fence-save" />
      </form>

      <form className="stack" aria-labelledby={`${id}-ch`} data-testid="contains-form" onSubmit={(e) => { e.preventDefault(); void check() }}>
        <h3 id={`${id}-ch`}>Which geofences contain a point?</h3>
        <PointInput legend="Point" testid="contains-point" value={point} onChange={setPoint} />
        <div><button type="submit" disabled={contains.busy || !llComplete(point)} data-testid="contains-run">Check</button></div>
        <Feedback a={contains} id="contains" />
        {inside && <p role="status" data-testid="contains-result">{inside.length ? `Inside: ${inside.join(', ')}` : 'Not inside any geofence.'}</p>}
      </form>
    </div>
  )
}
