import { useId, useState } from 'react'
import type { PreviewSession } from '../preview/previewSession'
import { boxQuery, formatAge, ageSeconds, WORLD, type Position } from '../map/mapLogic'
import { EMPTY_PLACE, llComplete, parseWhole, placeBody, placeDraft, pointQuery, toPt, type LL, type Place, type PlaceDraft } from './opsLogic'
import { FencesPanel } from './FencesPanel'
import { Confirm, Feedback, OpsPage, PointInput, State, isObj, isPage, must, useAction, useCall, useGet, type Call, type Page } from './opsShared'

interface PlaceHit extends Place { distance_m: number }
interface FenceEvent { id: string; subject_id: string; geofence_id: string; geofence_name: string; event: 'enter' | 'exit'; lat_micro: number; lng_micro: number; occurred_at: string }
const isHits = (j: unknown): boolean => isObj(j) && Array.isArray((j as { items?: unknown }).items)

function PlacesSection({ call }: { call: Call }) {
  const id = useId()
  const [kindText, setKindText] = useState('')
  const [kind, setKind] = useState('')
  const path = `/geo/places?limit=100&offset=0${kind ? `&kind=${encodeURIComponent(kind)}` : ''}`
  const [list, reload] = useGet<Page<Place>>(call, path, 'geo')
  const [draft, setDraft] = useState<PlaceDraft>(EMPTY_PLACE)
  const [confirm, setConfirm] = useState<Place | null>(null)
  const save = useAction()
  const del = useAction()
  const editing = draft.id !== null

  async function submit() {
    const b = placeBody(draft)
    if (!b.ok) { save.fail(b.error); return }
    await save.run(async () => {
      await must(call, editing ? 'PUT' : 'POST', editing ? `/geo/places/${draft.id}` : '/geo/places', b.body, 'geo')
      setDraft(EMPTY_PLACE); reload()
      return editing ? 'Place updated.' : 'Place created.'
    })
  }
  async function remove(p: Place) {
    const ok = await del.run(async () => { await must(call, 'DELETE', `/geo/places/${p.id}`, undefined, 'geo'); return `Deleted ${p.name}.` })
    setConfirm(null)
    if (ok) { if (draft.id === p.id) setDraft(EMPTY_PLACE); reload() }
  }

  return (
    <div className="stack" data-testid="places-section">
      <h2>Places</h2>
      <form className="hstack" aria-label="Filter places" data-testid="place-filter" onSubmit={(e) => { e.preventDefault(); setKind(kindText.trim()) }}>
        <label htmlFor={`${id}-kind`}>Kind</label>
        <input id={`${id}-kind`} value={kindText} maxLength={32} data-testid="place-filter-kind" onChange={(e) => setKindText(e.target.value)} />
        <button type="submit" className="outline" data-testid="place-filter-apply">Filter</button>
      </form>
      <State l={list} id="places" empty={(v) => !isPage(v) || v.items.length === 0} emptyText={kind ? `No places of kind ${kind}.` : 'No places yet. Add one below.'}>
        {(v) => (
          <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Places">
            <table className="stage-table" data-testid="place-table">
              <caption className="sr-only">Places{kind ? ` of kind ${kind}` : ''}, {v.total} in total</caption>
              <thead><tr><th scope="col">Name</th><th scope="col">Kind</th><th scope="col">Latitude</th><th scope="col">Longitude</th><th scope="col">Actions</th></tr></thead>
              <tbody>{v.items.map((p) => (
                <tr key={p.id} data-testid="place-row">
                  <th scope="row">{p.name}</th><td>{p.kind ?? ''}</td><td className="num">{p.lat}</td><td className="num">{p.lng}</td>
                  <td className="hstack">
                    <button type="button" className="outline" aria-label={`Edit ${p.name}`} data-testid="place-edit" onClick={() => { setDraft(placeDraft(p)); save.clear() }}>Edit</button>
                    <button type="button" className="outline" aria-label={`Delete ${p.name}`} data-testid="place-delete" disabled={del.busy} onClick={() => setConfirm(p)}>Delete</button>
                  </td>
                </tr>))}
              </tbody>
            </table>
          </div>
        )}
      </State>
      {confirm && <Confirm testid="place-confirm" busy={del.busy} yes="Yes, delete place" text={`Delete the place ${confirm.name}? This cannot be undone.`} onYes={() => void remove(confirm)} onNo={() => setConfirm(null)} />}
      <Feedback a={del} id="place-del" />

      <form className="stack" aria-labelledby={`${id}-h`} data-testid="place-form" onSubmit={(e) => { e.preventDefault(); void submit() }}>
        <h3 id={`${id}-h`}>{editing ? 'Edit place' : 'Add a place'}</h3>
        <div className="hstack">
          <label htmlFor={`${id}-name`}>Name</label>
          <input id={`${id}-name`} value={draft.name} maxLength={200} data-testid="place-name" onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          <label htmlFor={`${id}-pk`}>Kind (optional)</label>
          <input id={`${id}-pk`} value={draft.kind} maxLength={32} data-testid="place-kind" onChange={(e) => setDraft({ ...draft, kind: e.target.value })} />
        </div>
        <PointInput legend="Location" testid="place-point" value={draft.ll} onChange={(ll) => setDraft({ ...draft, ll })} />
        <div className="hstack">
          <button type="submit" disabled={save.busy} data-testid="place-save">{save.busy ? 'Saving…' : editing ? 'Save place' : 'Create place'}</button>
          {editing && <button type="button" className="outline" onClick={() => { setDraft(EMPTY_PLACE); save.clear() }}>Cancel edit</button>}
        </div>
        <Feedback a={save} id="place-save" />
      </form>
    </div>
  )
}

function QuerySection({ call }: { call: Call }) {
  const id = useId()
  const [mode, setMode] = useState<'nearest' | 'within'>('nearest')
  const [point, setPoint] = useState<LL>({ lat: null, lng: null })
  const [n, setN] = useState('5')
  const [radius, setRadius] = useState('1000')
  const [kind, setKind] = useState('')
  const [hits, setHits] = useState<PlaceHit[] | null>(null)
  const a = useAction()

  async function run() {
    const p = toPt(point)
    if (!p) { a.fail('Enter a latitude and a longitude.'); return }
    const q = [pointQuery(p)]
    if (mode === 'nearest') {
      const c = parseWhole(n, 1, 50)
      if (c === null) { a.fail('How many places: a whole number from 1 to 50.'); return }
      q.push(`n=${c}`)
    } else {
      const r = parseWhole(radius, 0, 20_000_000)
      if (r === null) { a.fail('Radius: a whole number of metres.'); return }
      q.push(`radius_m=${r}`)
    }
    if (kind.trim()) q.push(`kind=${encodeURIComponent(kind.trim())}`)
    setHits(null)
    await a.run(async () => {
      const j = await must(call, 'GET', `/geo/places/${mode}?${q.join('&')}`, undefined, 'geo')
      if (!isHits(j)) throw new Error('The API answered with something unexpected.')
      const r = j as { items: PlaceHit[]; truncated?: boolean }
      setHits(r.items)
      return r.truncated ? 'The result was cut off at the limit; narrow the query.' : undefined
    })
  }

  return (
    <form className="stack" aria-labelledby={`${id}-h`} data-testid="query-form" onSubmit={(e) => { e.preventDefault(); void run() }}>
      <h2 id={`${id}-h`}>Find places near a point</h2>
      <div className="hstack">
        <label htmlFor={`${id}-mode`}>Query</label>
        <select id={`${id}-mode`} value={mode} data-testid="query-mode" onChange={(e) => { setMode(e.target.value as 'nearest' | 'within'); setHits(null) }}>
          <option value="nearest">Nearest N</option><option value="within">Within a radius</option>
        </select>
        {mode === 'nearest'
          ? <><label htmlFor={`${id}-n`}>How many</label><input id={`${id}-n`} value={n} inputMode="numeric" data-testid="query-n" onChange={(e) => setN(e.target.value)} /></>
          : <><label htmlFor={`${id}-r`}>Radius (metres)</label><input id={`${id}-r`} value={radius} inputMode="numeric" data-testid="query-radius" onChange={(e) => setRadius(e.target.value)} /></>}
        <label htmlFor={`${id}-k`}>Kind (optional)</label>
        <input id={`${id}-k`} value={kind} maxLength={32} onChange={(e) => setKind(e.target.value)} />
      </div>
      <PointInput legend="Point" testid="query-point" value={point} onChange={setPoint} />
      <div><button type="submit" disabled={a.busy || !llComplete(point)} data-testid="query-run">{a.busy ? 'Searching…' : 'Search'}</button></div>
      <Feedback a={a} id="query" />
      {hits && (hits.length === 0 ? <p className="muted" data-testid="query-empty">No places found.</p> : (
        <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Query results">
          <table className="stage-table" data-testid="query-table">
            <caption className="sr-only">Places found, nearest first</caption>
            <thead><tr><th scope="col">Name</th><th scope="col">Kind</th><th scope="col">Distance (m)</th></tr></thead>
            <tbody>{hits.map((h) => <tr key={h.id} data-testid="query-row"><th scope="row">{h.name}</th><td>{h.kind ?? ''}</td><td className="num">{h.distance_m}</td></tr>)}</tbody>
          </table>
        </div>
      ))}
    </form>
  )
}

function EventsSection({ call }: { call: Call }) {
  const id = useId()
  const [text, setText] = useState('')
  const [subject, setSubject] = useState('')
  const path = `/geo/events?limit=50&offset=0${subject ? `&subject_id=${encodeURIComponent(subject)}` : ''}`
  const [list, reload] = useGet<Page<FenceEvent>>(call, path, 'geo')
  return (
    <div className="stack" data-testid="events-section">
      <h2>Geofence events</h2>
      <form className="hstack" aria-label="Filter events" onSubmit={(e) => { e.preventDefault(); setSubject(text.trim()) }}>
        <label htmlFor={`${id}-s`}>Subject</label>
        <input id={`${id}-s`} value={text} maxLength={128} data-testid="event-filter" onChange={(e) => setText(e.target.value)} />
        <button type="submit" className="outline">Filter</button>
        <button type="button" className="outline" onClick={reload} data-testid="events-refresh">Refresh</button>
      </form>
      <State l={list} id="events" empty={(v) => !isPage(v) || v.items.length === 0} emptyText="No enter or exit events yet.">
        {(v) => (
          <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Geofence events">
            <table className="stage-table" data-testid="event-table">
              <caption className="sr-only">Geofence enter and exit events, newest first</caption>
              <thead><tr><th scope="col">When</th><th scope="col">Subject</th><th scope="col">Geofence</th><th scope="col">Event</th></tr></thead>
              <tbody>{v.items.map((e) => <tr key={e.id} data-testid="event-row"><td>{e.occurred_at}</td><th scope="row">{e.subject_id}</th><td>{e.geofence_name}</td><td>{e.event}</td></tr>)}</tbody>
            </table>
          </div>
        )}
      </State>
    </div>
  )
}

interface HistoryRow { subject_id: string; seq: number; recorded_at: string; lat: string; lng: string }
function PositionsSection({ call, now }: { call: Call; now: () => number }) {
  const [list, reload] = useGet<{ items: Position[]; truncated?: boolean }>(call, `/location/positions?${boxQuery(WORLD)}&limit=100`, 'location')
  const [subject, setSubject] = useState<string | null>(null)
  const [hist] = useGet<{ items: HistoryRow[]; retention_cap: number }>(call, subject === null ? null : `/location/positions/${encodeURIComponent(subject)}/history?limit=50`, 'location')
  return (
    <div className="stack" data-testid="positions-section">
      <h2>Latest positions</h2>
      <div><button type="button" className="outline" onClick={reload} data-testid="positions-refresh">Refresh</button></div>
      <State l={list} id="positions" empty={(v) => !isPage(v) || v.items.length === 0} emptyText="No positions reported yet.">
        {(v) => (
          <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="Latest positions">
            <table className="stage-table" data-testid="position-table">
              <caption className="sr-only">Latest position of each subject{v.truncated ? ' (the list is cut off at the limit)' : ''}</caption>
              <thead><tr><th scope="col">Subject</th><th scope="col">Kind</th><th scope="col">Latitude</th><th scope="col">Longitude</th><th scope="col">Updated</th><th scope="col">History</th></tr></thead>
              <tbody>{v.items.map((p) => (
                <tr key={p.subject_id} data-testid="position-row">
                  <th scope="row">{p.subject_id}</th><td>{p.subject_kind ?? ''}</td><td className="num">{p.lat}</td><td className="num">{p.lng}</td><td>{formatAge(ageSeconds(p.updated_at, now()))}</td>
                  <td><button type="button" className="outline" aria-label={`History of ${p.subject_id}`} data-testid="position-history" onClick={() => setSubject(p.subject_id)}>History</button></td>
                </tr>))}
              </tbody>
            </table>
          </div>
        )}
      </State>
      {subject !== null && (
        <div className="stack" data-testid="history-panel">
          <h3>History of {subject}</h3>
          <State l={hist} id="history" empty={(v) => !isPage(v) || v.items.length === 0} emptyText="No history rows.">
            {(v) => (
              <ul data-testid="history-list">{v.items.map((h) => <li key={h.seq} data-testid="history-row">#{h.seq} {h.lat}, {h.lng} at {h.recorded_at}</li>)}</ul>
            )}
          </State>
          <div><button type="button" className="outline" onClick={() => setSubject(null)}>Close history</button></div>
        </div>
      )}
    </div>
  )
}

function Body({ session, now }: { session: PreviewSession; now: () => number }) {
  const call = useCall(session)
  const [events, setEvents] = useState(0)
  return (
    <>
      <PlacesSection call={call} />
      <QuerySection call={call} />
      <FencesPanel call={call} onChanged={() => setEvents((n) => n + 1)} />
      <EventsSection key={events} call={call} />
      <PositionsSection call={call} now={now} />
    </>
  )
}

export function PlacesPage({ projectId, session, now = Date.now }: { projectId: string; session?: PreviewSession; now?: () => number }) {
  return (
    <OpsPage projectId={projectId} session={session} testid="places-page" title="Places and geofences"
      intro="Named places, geofences (circle or polygon), proximity queries, enter and exit events and the latest positions of the generated project. Coordinates are decimal degrees here; the API stores integer micro-degrees.">
      {(s) => <Body key={projectId} session={s} now={now} />}
    </OpsPage>
  )
}
