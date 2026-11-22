import { useId, useState } from 'react'
import type { PreviewSession } from '../preview/previewSession'
import { EMPTY_LL, departIso, formatDistance, formatDuration, toPt, type LL } from './opsLogic'
import { Feedback, OpsPage, PointInput, isObj, must, useAction, useCall, type Call } from './opsShared'

type Mode = 'drive' | 'walk' | 'bike'
const needNum = (j: unknown, keys: string[]) => isObj(j) && keys.every((k) => typeof (j as Record<string, unknown>)[k] === 'number')

function Geocode({ call }: { call: Call }) {
  const id = useId()
  const [address, setAddress] = useState('')
  const [res, setRes] = useState<{ lat: string; lng: string; provider: string } | null>(null)
  const a = useAction()
  async function go() {
    if (!address.trim()) { a.fail('Enter an address.'); return }
    setRes(null)
    await a.run(async () => { setRes((await must(call, 'POST', '/geo/geocode', { address: address.trim() }, 'geo')) as { lat: string; lng: string; provider: string }) })
  }
  return (
    <form className="stack" aria-labelledby={`${id}-h`} data-testid="geocode-form" onSubmit={(e) => { e.preventDefault(); void go() }}>
      <h2 id={`${id}-h`}>Geocode an address</h2>
      <div className="hstack">
        <label htmlFor={`${id}-a`}>Address</label>
        <input id={`${id}-a`} value={address} maxLength={300} data-testid="geocode-address" onChange={(e) => setAddress(e.target.value)} />
        <button type="submit" disabled={a.busy} data-testid="geocode-run">{a.busy ? 'Looking up…' : 'Geocode'}</button>
      </div>
      <Feedback a={a} id="geocode" />
      {res && <p data-testid="geocode-result">Latitude {res.lat}, longitude {res.lng} (provider: {res.provider}).</p>}
    </form>
  )
}

function Trip({ call, kind }: { call: Call; kind: 'route' | 'eta' }) {
  const id = useId()
  const [from, setFrom] = useState<LL>(EMPTY_LL)
  const [to, setTo] = useState<LL>(EMPTY_LL)
  const [mode, setMode] = useState<Mode>('drive')
  const [depart, setDepart] = useState('')
  const [res, setRes] = useState<{ distance_m: number; duration_s: number; provider: string; arrives_at?: string } | null>(null)
  const a = useAction()
  async function go() {
    const o = toPt(from), d = toPt(to)
    if (!o || !d) { a.fail('Enter latitude and longitude for both the origin and the destination.'); return }
    const body: Record<string, unknown> = { origin: o, destination: d, mode }
    if (kind === 'eta') {
      const at = departIso(depart)
      if (at === undefined) { a.fail('The departure time is not a valid date and time.'); return }
      if (at !== null) body.depart_at = at
    }
    setRes(null)
    await a.run(async () => {
      const j = await must(call, 'POST', `/geo/${kind}`, body, 'geo')
      if (!needNum(j, ['distance_m', 'duration_s'])) throw new Error('The API answered with something unexpected.')
      setRes(j as typeof res)
    })
  }
  const title = kind === 'route' ? 'Route' : 'Estimated arrival (ETA)'
  return (
    <form className="stack" aria-labelledby={`${id}-h`} data-testid={`${kind}-form`} onSubmit={(e) => { e.preventDefault(); void go() }}>
      <h2 id={`${id}-h`}>{title}</h2>
      <PointInput legend="Origin" testid={`${kind}-origin`} value={from} onChange={setFrom} />
      <PointInput legend="Destination" testid={`${kind}-dest`} value={to} onChange={setTo} />
      <div className="hstack">
        <label htmlFor={`${id}-m`}>Mode</label>
        <select id={`${id}-m`} value={mode} data-testid={`${kind}-mode`} onChange={(e) => setMode(e.target.value as Mode)}>
          <option value="drive">Drive</option><option value="walk">Walk</option><option value="bike">Bike</option>
        </select>
        {kind === 'eta' && <><label htmlFor={`${id}-d`}>Depart at (optional)</label><input id={`${id}-d`} type="datetime-local" value={depart} data-testid="eta-depart" onChange={(e) => setDepart(e.target.value)} /></>}
        <button type="submit" disabled={a.busy} data-testid={`${kind}-run`}>{a.busy ? 'Working…' : kind === 'route' ? 'Get route' : 'Get ETA'}</button>
      </div>
      <Feedback a={a} id={kind} />
      {res && (
        <p data-testid={`${kind}-result`}>
          {formatDistance(res.distance_m)} ({res.distance_m} m), {formatDuration(res.duration_s)}
          {res.arrives_at ? `, arrives ${res.arrives_at}` : ''} (provider: {res.provider}).
        </p>
      )}
    </form>
  )
}

function Distance({ call }: { call: Call }) {
  const id = useId()
  const [pa, setA] = useState<LL>(EMPTY_LL)
  const [pb, setB] = useState<LL>(EMPTY_LL)
  const [res, setRes] = useState<number | null>(null)
  const a = useAction()
  async function go() {
    const x = toPt(pa), y = toPt(pb)
    if (!x || !y) { a.fail('Enter latitude and longitude for both points.'); return }
    setRes(null)
    await a.run(async () => {
      const j = await must(call, 'POST', '/geo/distance', { a: x, b: y }, 'geo')
      if (!needNum(j, ['distance_m'])) throw new Error('The API answered with something unexpected.')
      setRes((j as { distance_m: number }).distance_m)
    })
  }
  return (
    <form className="stack" aria-labelledby={`${id}-h`} data-testid="distance-form" onSubmit={(e) => { e.preventDefault(); void go() }}>
      <h2 id={`${id}-h`}>Distance between two points</h2>
      <PointInput legend="Point A" testid="distance-a" value={pa} onChange={setA} />
      <PointInput legend="Point B" testid="distance-b" value={pb} onChange={setB} />
      <div><button type="submit" disabled={a.busy} data-testid="distance-run">Measure</button></div>
      <Feedback a={a} id="distance" />
      {res !== null && <p data-testid="distance-result">{formatDistance(res)} ({res} m) along the great circle.</p>}
    </form>
  )
}

export function RoutingPage({ projectId, session }: { projectId: string; session?: PreviewSession }) {
  return (
    <OpsPage projectId={projectId} session={session} testid="routing-page" title="Route, ETA and geocode"
      intro="Geocoding, routing and arrival estimates come from a deterministic FAKE provider built into the generated project. They are repeatable test values, not real addresses, roads or traffic.">
      {(s) => <RoutingBody key={projectId} session={s} />}
    </OpsPage>
  )
}

function RoutingBody({ session }: { session: PreviewSession }) {
  const call = useCall(session)
  return (<><Geocode call={call} /><Trip call={call} kind="route" /><Trip call={call} kind="eta" /><Distance call={call} /></>)
}
