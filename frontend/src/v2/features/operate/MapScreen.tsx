import { useState } from 'react'
import { ageSeconds, clusterByGrid, dataPoints, fitBounds, formatPoint, freshness, geofencesContaining,
  makeProjection, VIEW_H, VIEW_W, WORLD, zoomBounds } from '../../../shell/map/mapLogic'
import type { Assignment, Bounds, Geofence, Place, Position } from '../../../shell/map/mapLogic'
import { useT } from '../../i18n'
import { Form } from '../../patterns'
import { Alert, Button, Checkbox, Grid, Row, Stack } from '../../ui'
import { segment, useRuntimeWrite } from './api/live'
import { canWrite } from './api/operate'
import { geographicIssue, subjectIssue, wholeIssue } from '../../validators/operateRuntime'
import type { LiveProps, Page, Session } from './api/live'
import { SectionLink, useOperateDate, useOperateSearch } from './components/Common'
import { Columns, data, Details, Empty, enumLabel, field, Filter, key, Panel, Refresh, RuntimeScreen, RuntimeState,
  optional, serverFields, text, useRuntimeQuery, WriteStatus } from './components/Runtime'
import './runtime.css'

type Subject = Omit<Position, 'seq'> & { seq: string }
type Event = { id: string; geofence_name: string; event: string; occurred_at: string }
const formatBounds = (bounds: Bounds) => [bounds.minLat, bounds.minLng, bounds.maxLat, bounds.maxLng].join(',')
function decodeBounds(value?: string, wraps = false): Bounds | undefined {
  const box = value?.split(',').map(Number)
  if (!box || box.length !== 4 || !box.every(Number.isSafeInteger)) return
  const [minLat, minLng, maxLat, maxLng] = box
  if (minLat < WORLD.minLat || maxLat > WORLD.maxLat || minLat >= maxLat ||
    Math.min(minLng, maxLng) < WORLD.minLng || Math.max(minLng, maxLng) > WORLD.maxLng || (!wraps && minLng >= maxLng)) return
  return { minLat, minLng, maxLat, maxLng }
}
export default function MapScreen(props: LiveProps) {
  return <RuntimeScreen id={props} title={'map'}>{session => <LiveMap session={session} writable={canWrite(props)} />}</RuntimeScreen>
}
function LiveMap({ session, writable }: { session: Session; writable: boolean }) {
  const t = useT()
  const date = useOperateDate()
  const { search, change } = useOperateSearch()
  const [auto, setAuto] = useState(false)
  const [boxError, setBoxError] = useState(false)
  const { minLat, minLng, maxLat, maxLng } = decodeBounds(search.box, true) ?? WORLD
  const poll = auto ? 10_000 : undefined
  const positions = useRuntimeQuery<{ items: Subject[]; truncated: boolean }>(session, '/location/positions', {
    min_lat_micro: minLat, min_lng_micro: minLng, max_lat_micro: maxLat, max_lng_micro: maxLng, limit: 500, subject_kind: search.kind,
  }, true, poll)
  const places = useRuntimeQuery<Page<Place>>(session, '/geo/places', { limit: 200 }, true, poll)
  const fences = useRuntimeQuery<Page<Geofence>>(session, '/geo/geofences', { limit: 200 }, true, poll)
  const offers = useRuntimeQuery<Page<Assignment>>(session, '/matching/assignments', { status: 'offered', limit: 100, candidate_id: search.subject }, true, poll)
  const subjects = positions.data?.items ?? []
  const geography = dataPoints(subjects, places.data?.items ?? [], fences.data?.items ?? [])
  const view = decodeBounds(search.viewport) ?? fitBounds(geography) ?? WORLD
  const project = makeProjection(view)
  const clusters = clusterByGrid(subjects.filter(p => p.lat_micro >= view.minLat && p.lat_micro <= view.maxLat &&
    p.lng_micro >= view.minLng && p.lng_micro <= view.maxLng), project)
  const now = positions.dataUpdatedAt
  const refresh = () => Promise.all([positions.refetch(), places.refetch(), fences.refetch(), offers.refetch()])
  const zoom = (bounds: Bounds) => change({ viewport: formatBounds(bounds) })
  return <Stack gap={4}>
    <Row><Refresh run={refresh} />
      <Checkbox checked={auto} onChange={event => setAuto(event.target.checked)} label={t(key('autoRefresh'))} />
      <SectionLink id={session.projectId} section="locationsettings" label={t(key('locationSettings'))} />
      <SectionLink id={session.projectId} section="geosettings" label={t(key('geoSettings'))} />
      <SectionLink id={session.projectId} section="matchingsettings" label={t(key('matchingSettings'))} />
    </Row>
    <Panel title={'positions'}>
      <Row><Button onClick={() => zoom(zoomBounds(view, 1, 2))}>{t(key('zoomIn'))}</Button>
        <Button onClick={() => zoom(zoomBounds(view, 2, 1))}>{t(key('zoomOut'))}</Button>
        <Button onClick={() => change({ viewport: undefined, box: undefined })}>{t(key('fit'))}</Button>
        <Button onClick={() => change({ box: formatBounds(view) })}>{t(key('loadArea'))}</Button>
        <Filter name="subjectKind" max={32} value={search.kind} onChange={kind => change({ kind, subject: undefined })} />
      </Row>
      <details><summary>{t(key('coordinateBox'))}</summary>
        <Form fields={['south', 'west', 'north', 'east'].map(name => field(t, name, { required: true, max: 12 }))}
          submitLabel={t(key('loadBox'))} formError={boxError ? t(key('boxError')) : undefined}
          onSubmit={form => {
            const parts = ['south', 'west', 'north', 'east'].map(name => text(form, name))
            const box = parts.map(value => /^-?\d+(?:\.\d{1,6})?$/.test(value) ? Math.round(Number(value) * 1_000_000) : NaN).join(',')
            const loaded = decodeBounds(box, true)
            setBoxError(!loaded)
            if (loaded) change({ box, viewport: loaded.minLng < loaded.maxLng ? box : undefined })
          }} />
      </details>
      {positions.isPending || positions.isError ? <RuntimeState error={positions.error} retry={positions.refetch} /> : <>
        {positions.data.truncated && <Alert tone="warning">{t(key('positionsTruncated'))}</Alert>}
        <p>{t(key('mapUpdated'), { date: date(now) })}</p>
        <div className="v2-runtime-map" role="group" aria-label={t(key('mapCanvas'))}>
          <svg className="v2-runtime-map-shapes" viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} aria-hidden="true">
            {fences.data?.items.map(fence => {
              if (fence.shape === 'circle' && fence.center && fence.radius_m) {
                const center = project.project(fence.center)
                return <circle key={fence.id} cx={center.x} cy={center.y} r={project.metresToPx(fence.radius_m)} />
              }
              if (fence.vertices) return <polygon key={fence.id} points={fence.vertices.map(point => {
                const { x, y } = project.project(point)
                return x + ',' + y
              }).join(' ')} />
              return null
            })}
            {places.data?.items.map(place => {
              const { x, y } = project.project(place)
              // gate-exempt: SVG view-box coordinates, independent of CSS pixel units.
              return <rect key={place.id} x={x - 5} y={y - 5} width={10} height={10} />
            })}
          </svg>
          {clusters.map(cluster => {
            const subject = cluster.items[0]
            const many = cluster.items.length > 1
            const short = subject.subject_id.slice(0, 2)
            const label = many ? t(key('cluster'), { count: cluster.items.length }) : t(key('marker'), { short, id: subject.subject_id })
            return <Button key={cluster.key} aria-label={label} aria-pressed={many ? undefined : subject.subject_id === search.subject}
              className="v2-runtime-marker" data-freshness={many ? undefined : freshness(ageSeconds(subject.recorded_at, now))}
              style={{ left: Math.min(93, Math.max(7, cluster.x / VIEW_W * 100)) + '%', top: Math.min(90, Math.max(10, cluster.y / VIEW_H * 100)) + '%' }}
              onClick={() => many ? zoom(fitBounds(cluster.items) ?? view) : change({ subject: subject.subject_id })}>
              {data(t, many ? cluster.items.length : short)}
            </Button>
          })}
        </div>
        {subjects.length ? <Columns label={'positions'} names={['subject', 'kind', 'coordinates', 'freshness', 'age', 'actions']} rows={subjects.map(p => ({
          id: p.subject_id, cells: [data(t, p.subject_id), data(t, p.subject_kind), data(t, formatPoint(p)), enumLabel(t, freshness(ageSeconds(p.recorded_at, now))), t(key('ageSeconds'), { seconds: ageSeconds(p.recorded_at, now) }),
            <Button onClick={() => change({ subject: p.subject_id })}>{t(key('open'))}</Button>],
        }))} /> : <Empty message="noPositions" onAction={positions.refetch} />}
      </>}
    </Panel>
    <Grid>
      <Panel title={'places'}>
        {places.isPending || places.isError ? <RuntimeState error={places.error} retry={places.refetch} /> : places.data.items.length ?
          <Columns label={'places'} names={['name', 'kind', 'coordinates']} rows={places.data.items.map(p => ({
            id: p.id, cells: [data(t, p.name), data(t, p.kind), data(t, formatPoint(p))],
          }))} /> : <Empty message="noPlaces" onAction={places.refetch} />}
        {places.data && places.data.total > places.data.items.length && <Alert tone="warning">{t(key('listTruncated'))}</Alert>}
      </Panel>
      <Panel title={'geofences'}>
        {fences.isPending || fences.isError ? <RuntimeState error={fences.error} retry={fences.refetch} /> : fences.data.items.length ?
          <Columns label={'geofences'} names={['name', 'shape']} rows={fences.data.items.map(f => ({ id: f.id, cells: [data(t, f.name), enumLabel(t, f.shape)] }))} /> :
          <Empty message="noFences" onAction={fences.refetch} />}
        {fences.data && fences.data.total > fences.data.items.length && <Alert tone="warning">{t(key('listTruncated'))}</Alert>}
      </Panel>
    </Grid>
    {writable && <ReportPosition session={session} />}
    {search.subject && <SubjectDetails key={search.subject} session={session} id={search.subject} fences={fences.data?.items ?? []} offers={offers} />}
  </Stack>
}
function SubjectDetails({ session, id, fences, offers }: { session: Session; id: string; fences: Geofence[]; offers: ReturnType<typeof useRuntimeQuery<Page<Assignment>>> }) {
  const t = useT()
  const date = useOperateDate()
  const { change } = useOperateSearch()
  const path = `/location/positions/${segment(id)}` as const
  const position = useRuntimeQuery<Subject>(session, path)
  const history = useRuntimeQuery<{ items: Subject[]; retention_cap: number }>(session, `${path}/history`, { limit: 100 })
  const events = useRuntimeQuery<Page<Event>>(session, '/geo/events', { subject_id: id, limit: 100 })
  return <Panel title={'subject'}>
    <Row><Button onClick={() => change({ subject: undefined })}>{t(key('clearSelection'))}</Button></Row>
    {position.isPending || position.isError ? <RuntimeState error={position.error} retry={position.refetch} /> :
      <Details values={[[ 'subject', data(t, position.data.subject_id)], ['kind', data(t, position.data.subject_kind)],
        ['coordinates', data(t, formatPoint(position.data))], ['recorded', date(position.data.recorded_at)],
        ['sequence', data(t, position.data.seq)], ['inside', data(t, geofencesContaining(position.data, fences).map(f => f.name).join(', '))]]} />}
    <h3>{t(key('offers'))}</h3>
    {offers.isPending || offers.isError ? <RuntimeState error={offers.error} retry={offers.refetch} /> : offers.data.items.length ?
      <Columns label={'offers'} names={['reference', 'score', 'distance', 'expires']} rows={offers.data.items.map(o => ({
        id: o.id, cells: [data(t, o.request_ref), data(t, o.score), data(t, o.distance_m), date(o.expires_at)],
      }))} /> : <Empty message="noOffers" onAction={offers.refetch} />}
    <h3>{t(key('history'))}</h3>
    {history.isPending || history.isError ? <RuntimeState error={history.error} retry={history.refetch} /> :
      <Columns label={'history'} names={['recorded', 'sequence', 'coordinates']} rows={history.data.items.map(p => ({
        id: p.seq, cells: [date(p.recorded_at), data(t, p.seq), data(t, formatPoint(p))],
      }))} />}
    <h3>{t(key('events'))}</h3>
    {events.isPending || events.isError ? <RuntimeState error={events.error} retry={events.refetch} /> :
      <Columns label={'events'} names={['geofences', 'status', 'date']} rows={events.data.items.map(e => ({
        id: e.id, cells: [data(t, e.geofence_name), enumLabel(t, e.event), date(e.occurred_at)],
      }))} />}
  </Panel>
}

type PositionInput = { subject_id: string; subject_kind?: string; lat: string; lng: string; seq: number; recorded_at?: string }
type PositionResult = { applied: boolean; position: Subject }
function ReportPosition({ session }: { session: Session }) {
  const t = useT()
  const { change } = useOperateSearch()
  const mutation = useRuntimeWrite<PositionInput, PositionResult>(session, '/location/positions')
  return <Panel title={'reportPosition'}>
    <Form fields={[
      field(t, 'subject', { required: true, max: 128, validate: subjectIssue }),
      field(t, 'subjectKind', { max: 32 }),
      field(t, 'latitude', { required: true, max: 12, validate: v => geographicIssue(v, 90) }),
      field(t, 'longitude', { required: true, max: 12, validate: v => geographicIssue(v, 180) }),
      field(t, 'sequence', { required: true, max: 16, validate: v => wholeIssue(v, 0, Number.MAX_SAFE_INTEGER) }),
      field(t, 'recorded', { type: 'datetime-local' }),
    ]} serverErrors={serverFields(mutation.error, { subject_id: 'subject', subject_kind: 'subjectKind', lat: 'latitude', lng: 'longitude', seq: 'sequence', recorded_at: 'recorded' })}
      submitLabel={t(key('reportPosition'))} pending={mutation.isPending} onSubmit={form => {
      const recorded = optional(form, 'recorded')
      mutation.mutate({ subject_id: text(form, 'subject'), subject_kind: optional(form, 'subjectKind'),
        lat: text(form, 'latitude'), lng: text(form, 'longitude'), seq: Number(text(form, 'sequence')),
        recorded_at: recorded ? new Date(recorded).toISOString() : undefined,
      }, { onSuccess: ({ data }) => change({ subject: data.position.subject_id }) })
    }} />
    {mutation.data && !mutation.data.data.applied && <Alert tone="warning">{t(key('stalePosition'))}</Alert>}
    <WriteStatus error={mutation.error} reload={mutation.reset}
      success={mutation.data?.data.applied ? t(key('positionReported')) : undefined} />
  </Panel>
}
