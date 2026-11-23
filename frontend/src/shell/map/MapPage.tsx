import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { PreviewSessionGate } from '../preview/PreviewSessionGate'
import { usePreviewSession } from '../preview/usePreviewSession'
import type { PreviewSession } from '../preview/previewSession'
import {
  VIEW_H, VIEW_W, WORLD, ageSeconds, boxQuery, clusterByGrid, dataPoints, fitBounds, formatAge, formatPoint, freshness, geoErrorMessage,
  geofencesContaining, makeProjection, zoomBounds,
  type Assignment, type Bounds, type Geofence, type Place, type Position,
} from './mapLogic'

const isPage = (j: unknown): boolean => !!j && typeof j === 'object' && Array.isArray((j as { items?: unknown }).items)
type Page<T> = { items: T[]; total?: number; truncated?: boolean }
type Load<T> = { s: 'idle' } | { s: 'loading' } | { s: 'off' } | { s: 'error'; m: string } | { s: 'ok'; v: T }

const msg = (e: unknown, f: string) => (e instanceof Error ? e.message : f)
const FRESH_COLOR: Record<string, string> = { fresh: '#1a7f37', aging: '#9a6700', stale: '#6e7781' }

/** Map view for a generated project's operations pack (geo D13, location D14, matching D15). Pure SVG: no tiles, no map library,
 *  no network besides the project API. Uses the dashboard-supplied preview session (tokens kept in memory only, never shown). */
function MapPageBody({ session, pollMs = 10_000, now = Date.now }: { projectId: string; session: PreviewSession; pollMs?: number; now?: () => number }) {
  const { request } = session
  const [positions, setPositions] = useState<Load<Page<Position>>>({ s: 'idle' })
  const [fences, setFences] = useState<Load<Page<Geofence>>>({ s: 'idle' })
  const [places, setPlaces] = useState<Load<Page<Place>>>({ s: 'idle' })
  const [assignments, setAssignments] = useState<Load<Page<Assignment>>>({ s: 'idle' })
  const [box, setBox] = useState<Bounds>(WORLD)
  const [view, setView] = useState<Bounds | null>(null) // null = auto-fit to data
  const [selected, setSelected] = useState<string | null>(null)
  const [refresh, setRefresh] = useState(0)
  const [auto, setAuto] = useState(false)
  const [stamp, setStamp] = useState(0)
  const autoId = useId()
  const nowRef = useRef(now)
  nowRef.current = now

  const call = useCallback(async (path: string) => {
    const r = await request('GET', path)
    let json: unknown = null
    try { json = r.text ? JSON.parse(r.text) : null } catch { json = null }
    return { status: r.status, json }
  }, [request])


  const get = useCallback(async <T,>(path: string, set: (l: Load<T>) => void, off: () => boolean, keep: boolean) => {
    if (!keep) set({ s: 'loading' })
    try {
      const r = await call(path)
      if (off()) return
      if (r.status >= 200 && r.status < 300) {
        if (isPage(r.json)) set({ s: 'ok', v: r.json as T })
        else set({ s: 'error', m: 'The project API answered with something unexpected. Check that this is the generated project API.' })
      }
      else if (r.status === 404) set({ s: 'off' }) // block not declared in this project's spec
      else set({ s: 'error', m: geoErrorMessage(r.status, r.json) })
    } catch (e) { if (!off()) set({ s: 'error', m: msg(e, 'Could not reach the project API') }) }
  }, [call])

  useEffect(() => {
    let dead = false
    const off = () => dead
    const keep = positions.s === 'ok' // background refreshes keep the markers on screen
    void get<Page<Position>>(`/location/positions?${boxQuery(box)}&limit=500`, (l) => { setPositions(l); if (l.s === 'ok') setStamp(nowRef.current()) }, off, keep)
    void get<Page<Geofence>>('/geo/geofences?limit=200', setFences, off, fences.s === 'ok')
    void get<Page<Place>>('/geo/places?limit=200', setPlaces, off, places.s === 'ok')
    void get<Page<Assignment>>('/matching/assignments?limit=100&status=offered', setAssignments, off, assignments.s === 'ok')
    return () => { dead = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, box, get])

  // auto-poll: only while the tab is visible; coming back refreshes once
  useEffect(() => {
    if (!auto) return
    let timer: ReturnType<typeof setInterval> | null = null
    const start = () => { if (timer === null) timer = setInterval(() => setRefresh((n) => n + 1), pollMs) }
    const stop = () => { if (timer !== null) { clearInterval(timer); timer = null } }
    const onVis = () => { if (document.hidden) stop(); else { setRefresh((n) => n + 1); start() } }
    if (!document.hidden) start()
    document.addEventListener('visibilitychange', onVis)
    return () => { stop(); document.removeEventListener('visibilitychange', onVis) }
  }, [auto, pollMs])

  const posItems = positions.s === 'ok' ? positions.v.items : []
  const fenceItems = fences.s === 'ok' ? fences.v.items : []
  const placeItems = places.s === 'ok' ? places.v.items : []
  const asgItems = assignments.s === 'ok' ? assignments.v.items : []

  const fitted = useMemo(() => fitBounds(dataPoints(posItems, placeItems, fenceItems)), [posItems, placeItems, fenceItems])
  const bounds = view ?? fitted ?? WORLD
  const proj = useMemo(() => makeProjection(bounds), [bounds])
  const visible = useMemo(() => posItems.filter((p) => proj.inView(p)), [posItems, proj])
  const clusters = useMemo(() => clusterByGrid(visible, proj, 44), [visible, proj])
  const nowMs = stamp || now()
  const sel = posItems.find((p) => p.subject_id === selected) ?? null
  const selFences = sel ? geofencesContaining(sel, fenceItems) : []
  const selAsg = sel ? asgItems.filter((a) => a.candidate_id === sel.subject_id) : []
  const reload = () => setRefresh((n) => n + 1)

  return (
    <>

      {(
        <>
          <div className="hstack" role="group" aria-label="Map controls" data-testid="map-controls">
            <button type="button" className="outline" onClick={reload} data-testid="map-refresh">Refresh</button>
            <span className="hstack">
              <input id={autoId} type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} data-testid="map-auto" />
              <label htmlFor={autoId}>Auto-refresh every {Math.round(pollMs / 1000)} s (pauses while this tab is hidden)</label>
            </span>
            <button type="button" className="ghost small" onClick={() => setView(zoomBounds(bounds, 1, 2))} data-testid="map-zoom-in">Zoom in</button>
            <button type="button" className="ghost small" onClick={() => setView(zoomBounds(bounds, 2, 1))} data-testid="map-zoom-out">Zoom out</button>
            <button type="button" className="ghost small" onClick={() => { setView(null); setBox(WORLD) }} data-testid="map-fit">Fit to data</button>
            <button type="button" className="ghost small" onClick={() => setBox(bounds)} data-testid="map-load-area">Load only this area</button>
            {stamp > 0 && <span className="small-text muted" data-testid="map-updated">Updated {new Date(stamp).toISOString().slice(11, 19)} UTC</span>}
          </div>

          <Status l={positions} id="map-positions" label="locations" />
          {positions.s === 'ok' && positions.v.truncated && <p role="status" className="muted" data-testid="map-truncated">Only the first 500 positions are shown. Use &quot;Load only this area&quot; to narrow it down.</p>}
          {fences.s === 'off' && <p className="muted small-text" data-testid="map-geo-off">Geofences are not enabled in this project.</p>}
          {fences.s === 'error' && <p role="alert" className="error-text" data-testid="map-fences-error">{fences.m}</p>}
          {places.s === 'error' && <p role="alert" className="error-text" data-testid="map-places-error">{places.m}</p>}
          {assignments.s === 'error' && <p role="alert" className="error-text" data-testid="map-assignments-error">{assignments.m}</p>}

          {positions.s === 'ok' && posItems.length === 0 && <p className="muted" data-testid="map-positions-empty">No live locations in this area yet. Subjects appear after they POST /location/positions.</p>}

          <div className="hstack" style={{ alignItems: 'flex-start', gap: '1rem', flexWrap: 'wrap' }}>
            <div style={{ flex: '2 1 480px', minWidth: 0 }}>
              <div role="group" aria-label="Map canvas" data-testid="map-canvas" style={{ position: 'relative', width: '100%', aspectRatio: `${VIEW_W} / ${VIEW_H}`, background: '#eef2f6', border: '1px solid #c9d1d9', borderRadius: 6, overflow: 'hidden' }}>
                <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} preserveAspectRatio="none" width="100%" height="100%" aria-hidden="true" focusable="false" style={{ position: 'absolute', inset: 0 }} data-testid="map-svg">
                  {fenceItems.map((g) => {
                    if (g.shape === 'circle' && g.center && g.radius_m) {
                      const c = proj.project(g.center)
                      return <circle key={g.id} cx={c.x} cy={c.y} r={Math.max(2, proj.metresToPx(g.radius_m))} fill="rgba(9,105,218,0.12)" stroke="#0969da" strokeWidth={2} data-testid="map-fence-circle" data-fence={g.id} />
                    }
                    if (g.shape === 'polygon' && g.vertices) {
                      const pts = g.vertices.map((v) => { const q = proj.project(v); return `${q.x},${q.y}` }).join(' ')
                      return <polygon key={g.id} points={pts} fill="rgba(130,80,223,0.12)" stroke="#8250df" strokeWidth={2} data-testid="map-fence-polygon" data-fence={g.id} />
                    }
                    return null
                  })}
                  {placeItems.filter((p) => proj.inView(p)).map((p) => {
                    const q = proj.project(p)
                    return <rect key={p.id} x={q.x - 5} y={q.y - 5} width={10} height={10} fill="#bc4c00" data-testid="map-place" data-place={p.id} />
                  })}
                </svg>
                {clusters.map((c) => {
                  const single = c.items.length === 1
                  const p = c.items[0]
                  const isSel = single && p.subject_id === selected
                  const fr = single ? freshness(ageSeconds(p.recorded_at, nowMs)) : 'fresh'
                  const label = single
                    ? `${p.subject_id}${p.subject_kind ? ` (${p.subject_kind})` : ''}, ${formatPoint(p)}, ${formatAge(ageSeconds(p.recorded_at, nowMs))}${fr === 'stale' ? ', stale' : ''}`
                    : `Cluster of ${c.items.length} subjects, press to zoom in`
                  return (
                    <button
                      key={c.key}
                      type="button"
                      aria-label={label}
                      aria-pressed={single ? isSel : undefined}
                      data-testid={single ? 'map-marker' : 'map-cluster'}
                      data-subject={single ? p.subject_id : undefined}
                      data-freshness={single ? fr : undefined}
                      data-count={single ? undefined : c.items.length}
                      onClick={() => {
                        if (single) setSelected(p.subject_id)
                        else { const b = fitBounds(c.items); if (b) setView(b) }
                      }}
                      style={{
                        position: 'absolute', left: `${(c.x / VIEW_W) * 100}%`, top: `${(c.y / VIEW_H) * 100}%`, transform: 'translate(-50%, -50%)',
                        width: single ? 22 : 34, height: single ? 22 : 34, minWidth: 0, padding: 0, lineHeight: 1, borderRadius: '50%', cursor: 'pointer',
                        color: '#fff', fontSize: 12, fontWeight: 700, background: single ? FRESH_COLOR[fr] : '#0969da',
                        opacity: single && fr === 'stale' ? 0.55 : 1, border: isSel ? '3px solid #000' : '2px solid #fff',
                        borderStyle: single && fr === 'stale' ? 'dashed' : 'solid',
                      }}
                    >{single ? '' : c.items.length}</button>
                  )
                })}
              </div>
              <p className="small-text muted" data-testid="map-legend">
                Markers: green = updated under a minute ago, amber = under 5 minutes, grey dashed = stale. Blue circles are clusters; press one to zoom in. Squares are places; outlines are geofences.
              </p>
            </div>

            <div style={{ flex: '1 1 260px', minWidth: 0 }}>
              <h2>Subjects ({posItems.length})</h2>
              <ul className="stack" style={{ listStyle: 'none', padding: 0, margin: 0 }} aria-label="Live locations" data-testid="map-list">
                {posItems.map((p) => {
                  const age = ageSeconds(p.recorded_at, nowMs)
                  const fr = freshness(age)
                  return (
                    <li key={p.subject_id}>
                      <button type="button" className={p.subject_id === selected ? '' : 'outline'} aria-pressed={p.subject_id === selected} onClick={() => setSelected(p.subject_id)} data-testid="map-list-item" data-subject={p.subject_id} data-freshness={fr} style={{ width: '100%', textAlign: 'left' }}>
                        <strong>{p.subject_id}</strong>{p.subject_kind ? ` (${p.subject_kind})` : ''}<br />
                        <span className="small-text">{formatPoint(p)} · {formatAge(age)}{fr === 'stale' ? ' · stale' : ''}</span>
                      </button>
                    </li>
                  )
                })}
              </ul>
              {sel && (
                <div role="region" aria-label={`Details of ${sel.subject_id}`} data-testid="map-details" className="stack">
                  <h2>{sel.subject_id}</h2>
                  <p className="small-text">Position {formatPoint(sel)}, sequence {sel.seq}, recorded {sel.recorded_at}.</p>
                  <p className="small-text" data-testid="map-details-fences">
                    {fences.s !== 'ok' ? 'Geofences unavailable.' : selFences.length ? `Inside: ${selFences.map((g) => g.name).join(', ')}` : 'Inside no geofence.'}
                  </p>
                  <div data-testid="map-details-assignments">
                    {assignments.s === 'off' ? <p className="small-text muted">Matching is not enabled in this project.</p>
                      : selAsg.length === 0 ? <p className="small-text muted">No open assignment offers.</p>
                        : <ul>{selAsg.map((a) => <li key={a.id} data-testid="map-assignment">Request {a.request_ref}: {a.status}, {a.distance_m} m away, score {a.score}</li>)}</ul>}
                  </div>
                  <button type="button" className="ghost small" onClick={() => setSelected(null)} data-testid="map-details-close">Clear selection</button>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </>
  )
}

export function MapPage({ projectId, session, pollMs, now }: { projectId: string; session?: PreviewSession; pollMs?: number; now?: () => number }) {
  const own = usePreviewSession(projectId, { disabled: !!session })
  const s = session ?? own
  return (
    <section aria-labelledby="map-h" data-testid="map-page" className="stack">
      <h1 id="map-h">Map</h1>
      <p className="muted">Live positions, places and geofences of the running project, drawn on a plain canvas (no map tiles are loaded).</p>
      <PreviewSessionGate session={s} prefix="map">
        <MapPageBody key={projectId} projectId={projectId} session={s} pollMs={pollMs} now={now}/>
      </PreviewSessionGate>
    </section>
  )
}

function Status<T>({ l, id, label }: { l: Load<T>; id: string; label: string }) {
  if (l.s === 'loading') return <p role="status" className="muted" data-testid={`${id}-loading`}>Loading {label}…</p>
  if (l.s === 'error') return <p role="alert" className="error-text" data-testid={`${id}-error`}>{l.m}</p>
  if (l.s === 'off') return <p className="muted" data-testid={`${id}-off`}>The location block is not enabled in this project.</p>
  return null
}
