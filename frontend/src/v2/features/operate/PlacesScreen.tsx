import { useReducer, useState } from 'react'
import { useT } from '../../i18n'
import { ConfirmDestructive, Form } from '../../patterns'
import { Alert, Button, Grid, Row, Stack, Tabs } from '../../ui'
import { noNullIssue, subjectIssue, wholeIssue } from '../../validators/operateRuntime'
import { formatMicro } from '../../../shell/operations/opsLogic'
import type { FenceBody } from '../../../shell/operations/opsLogic'
import { ageSeconds, formatAge } from '../../../shell/map/mapLogic'
import { useRuntimeWrite } from './api/live'
import type { LiveProps, Page, Session } from './api/live'
import { canWrite } from './api/operate'
import { geoPath, positionPath } from './api/tools'
import type { Fence, FenceEvent, Place, PlaceHits, Point, Position, PositionHistory, Positions } from './api/tools'
import { useOperateDate, useOperateSearch } from './components/Common'
import { Columns, data, Details, Empty, enumLabel, field, Filter, key, optional, Pager, Panel, Pick, Refresh, RuntimeState, serverFields, text, useRuntimeQuery, WriteStatus } from './components/Runtime'
import { pointFields, PointGroup, readPoint, ToolsLinks, world } from './components/RuntimeTools'
import { CoordinatePlot } from './components/CoordinatePlot'
import { ToolScreen } from './components/ToolScreen'
import { initialVertices, vertices } from './state/vertices'

type Collection = 'places' | 'geofences'
const tabs = ['places', 'geofences', 'fenceEvents', 'latestPositions']
const defaultRadius = 20_000_000

export default function PlacesScreen(props: LiveProps) {
  return <ToolScreen id={props} title={'places'}>{session => <Places session={session} writable={canWrite(props)} />}</ToolScreen>
}

function Places({ session, writable }: { session: Session; writable: boolean }) {
  const t = useT()
  const { search, change } = useOperateSearch()
  const tab = tabs.includes(search.tab ?? '') ? search.tab! : 'places'
  return <Stack gap={4}>
    <ToolsLinks session={session} sections={['geosettings', 'locationsettings', 'routing', 'map']} />
    <Tabs label={t(key('geoViews'))} value={tab} onChange={tab => change({ tab, page: undefined, edit: undefined, kind: undefined, subject: undefined, fence: undefined, q: undefined })}
      items={[
        { id: 'places', label: t(key('savedPlaces')), content: <Stack><CollectionList collection="places" session={session} writable={writable} /><Nearby session={session} /></Stack> },
        { id: 'geofences', label: t(key('geofences')), content: <Stack><CollectionList collection="geofences" session={session} writable={writable} />
          <PointCheck session={session} />{writable && <PointCheck session={session} evaluate />}</Stack> },
        { id: 'fenceEvents', label: t(key('fenceEvents')), content: <Events session={session} /> },
        { id: 'latestPositions', label: t(key('latestPositions')), content: <PositionsPanel session={session} /> },
      ]} />
  </Stack>
}

const isPlace = (row: Place | Fence): row is Place => 'lat_micro' in row
function CollectionList({ collection, session, writable }: { collection: Collection; session: Session; writable: boolean }) {
  const t = useT()
  const date = useOperateDate()
  const { search, change } = useOperateSearch()
  const isPlaces = collection === 'places'
  const title = isPlaces ? 'savedPlaces' : 'geofences'
  const page = search.page ?? 1
  const size = 100
  const query = useRuntimeQuery<Page<Place | Fence>>(session, `/geo/${collection}`, {
    limit: size, offset: (page - 1) * size, kind: isPlaces ? search.kind : undefined,
  })
  const editing = search.edit && search.edit !== 'new'
  const detail = useRuntimeQuery<Place | Fence>(session, geoPath(collection, editing ? search.edit! : ''), {}, !!editing)
  const add = isPlaces ? 'addPlace' : 'addFence'
  const open = (id?: string) => change({ edit: id })
  const rows = query.data?.items ?? []
  return <Stack>
    <Panel title={title}>
      <Row>
        {isPlaces && <Filter name="kind" value={search.kind} max={32} onChange={kind => change({ kind, page: undefined })} />}
        <Refresh run={query.refetch} />{writable && !!rows.length && <Button onClick={() => open('new')}>{t(key(add))}</Button>}
      </Row>
      {query.isPending || query.isError ? <RuntimeState error={query.error} retry={query.refetch} /> :
        rows.length ? <Columns label={title} names={isPlaces ? ['name', 'kind', 'lat', 'lng', 'actions'] : ['name', 'shape', 'extent', 'actions']}
          rows={rows.map(row => ({
            id: row.id,
            cells: [data(t, row.name), ...(isPlace(row) ? [data(t, row.kind), data(t, row.lat), data(t, row.lng)] :
              [enumLabel(t, row.shape), row.center ? t(key('circleExtent'), { lat: row.center.lat, lng: row.center.lng, radius: row.radius_m ?? 0 }) :
                t(key('vertexCount'), { count: row.vertices?.length ?? 0 })]),
              <Row><Button aria-expanded={search.edit === row.id} onClick={() => open(search.edit === row.id ? undefined : row.id)}>{t(key(writable ? 'edit' : 'open'))}</Button>
                {writable && <RemoveGeo collection={collection} session={session} row={row} after={() => { if (search.edit === row.id) open() }} />}</Row>],
          }))} /> : <Empty message={isPlaces ? 'noPlaces' : 'noFences'} action={writable ? add : undefined} onAction={writable ? () => open('new') : query.refetch} />}
      {rows.length > 0 && <CoordinatePlot label={isPlaces ? 'placesPlot' : 'fencesPlot'}
        points={rows.filter(isPlace).map(point => ({ id: point.id, point, name: point.name }))}
        fences={rows.filter((row): row is Fence => !isPlace(row))} />}
      <Pager label={title} page={page} size={size} total={query.data?.total ?? 0} change={page => change({ page })} />
    </Panel>
    {search.edit && (editing || writable) && <Panel title={editing ? isPlaces ? 'placeDetail' : 'fenceDetail' : add}>
      <Row><Button onClick={() => open()}>{t(key('close'))}</Button></Row>
      {editing && (detail.isPending || detail.isError) ? <RuntimeState error={detail.error} retry={detail.refetch} /> : <>
        {detail.data && <Details values={[
          ['name', data(t, detail.data.name)], ['created', date(detail.data.created_at)],
          ...(isPlace(detail.data) ? [['lat', data(t, detail.data.lat)], ['lng', data(t, detail.data.lng)]] :
            [['shape', enumLabel(t, detail.data.shape)], ['extent', data(t, detail.data.center ?
              t(key('circleExtent'), { lat: detail.data.center.lat, lng: detail.data.center.lng, radius: detail.data.radius_m ?? 0 }) :
              detail.data.vertices?.map(point => point.lat + ', ' + point.lng).join(' · '))]]) as [string, string][],
        ]} />}
        {writable && (isPlaces ? <PlaceEditor key={search.edit} session={session} row={detail.data && isPlace(detail.data) ? detail.data : undefined} /> :
          <FenceEditor key={search.edit} session={session} row={detail.data && !isPlace(detail.data) ? detail.data : undefined} />)}
      </>}
    </Panel>}
  </Stack>
}

function RemoveGeo({ collection, session, row, after }: { collection: Collection; session: Session; row: Place | Fence; after: () => void }) {
  const t = useT()
  const write = useRuntimeWrite<undefined, null>(session, geoPath(collection, row.id), 'DELETE')
  const action = t(key('delete'))
  return <Stack>
    <ConfirmDestructive trigger={<Button variant="danger">{action}</Button>} title={t(key('deleteNamed'), { name: row.name })}
      description={t(key('deleteGeoHelp'))} action={action} pending={write.isPending} onConfirm={async () => {
        await write.mutateAsync(undefined)
        after()
      }} />
    <WriteStatus error={write.error} reload={write.reset} />
  </Stack>
}

function PlaceEditor({ session, row }: { session: Session; row?: Place }) {
  const t = useT()
  const write = useRuntimeWrite<Point & { name: string; kind: string | null }, Place>(session, row ? geoPath('places', row.id) : '/geo/places', row ? 'PUT' : 'POST')
  return <Stack>
    <Form fields={[
      field(t, 'name', { value: row?.name, required: true, max: 200, validate: noNullIssue }),
      field(t, 'kind', { value: row?.kind ?? '', max: 32, validate: noNullIssue }),
      ...pointFields(t, 'place', row),
    ]} pending={write.isPending} submitLabel={t(key(row ? 'savePlace' : 'createPlace'))}
      serverErrors={serverFields(write.error, { lat_micro: 'placelat', lng_micro: 'placelng' })}
      onSubmit={form => write.mutate({ ...readPoint(form, 'place'), name: text(form, 'name'), kind: optional(form, 'kind') ?? null })} />
    <WriteStatus error={write.error} reload={write.reset} success={write.data ? t(key('placeSaved')) : undefined} />
  </Stack>
}

function FenceEditor({ session, row }: { session: Session; row?: Fence }) {
  const t = useT()
  const [shape, setShape] = useState(row?.shape ?? 'circle')
  const [draft, dispatch] = useReducer(vertices, row?.vertices, initialVertices)
  const write = useRuntimeWrite<FenceBody, Fence>(session, row ? geoPath('geofences', row.id) : '/geo/geofences', row ? 'PUT' : 'POST')
  const isCircle = shape === 'circle'
  const coords = (p: string, point?: Fence['center']) => pointFields(t, p, point ?? undefined)
  return <Stack>
    <Pick label={t(key('shape'))} value={shape} options={['circle', 'polygon'].map(value => ({ value, label: enumLabel(t, value) }))}
      onChange={value => setShape(value === 'polygon' ? 'polygon' : 'circle')} />
    <Form fields={[
      field(t, 'name', { value: row?.name, max: 200, required: true, validate: noNullIssue }),
      ...(isCircle ? [...coords('center', row?.center), field(t, 'radius', { value: String(row?.radius_m ?? ''), validate: value => wholeIssue(value, 1, defaultRadius) })] :
        draft.items.flatMap(vertex => coords('vertex' + vertex.id, vertex.point))),
    ]} layout={controls => <Stack>{controls.name}
      {isCircle ? <PointGroup label={'center'}><Grid>{controls.centerlat}{controls.centerlng}{controls.radius}</Grid></PointGroup> :
        <PointGroup label={'polygonVertices'}>
          {draft.items.map(({ id }, index) => <Grid key={id}>
            {controls['vertex' + id + 'lat']}{controls['vertex' + id + 'lng']}
            <Row>
              <Button disabled={!index || write.isPending} onClick={() => dispatch({ type: 'move', id, direction: -1 })}>{t(key('up'))}</Button>
              <Button disabled={index === draft.items.length - 1 || write.isPending} onClick={() => dispatch({ type: 'move', id, direction: 1 })}>{t(key('down'))}</Button>
              <ConfirmDestructive trigger={<Button variant="danger" disabled={draft.items.length <= 3 || write.isPending}>{t(key('remove'))}</Button>}
                title={t(key('removeVertex'))} description={t(key('removeVertexHelp'))} action={t(key('remove'))}
                onConfirm={() => dispatch({ type: 'remove', id })} />
            </Row>
          </Grid>)}
          <Row><Button disabled={write.isPending || draft.items.length >= 200} onClick={() => dispatch({ type: 'add' })}>{t(key('addVertex'))}</Button></Row>
        </PointGroup>}
    </Stack>} pending={write.isPending} submitLabel={t(key(row ? 'saveFence' : 'createFence'))} serverErrors={serverFields(write.error, {
      radius_m: 'radius', 'center.lat_micro': 'centerlat', 'center.lng_micro': 'centerlng',
    })} onSubmit={form => {
      const name = text(form, 'name')
      write.mutate(isCircle ? { name, shape: 'circle', center: readPoint(form, 'center'), radius_m: Number(text(form, 'radius')) } :
        { name, shape: 'polygon', vertices: draft.items.map(vertex => readPoint(form, 'vertex' + vertex.id)) })
    }} />
    <WriteStatus error={write.error} reload={write.reset} success={write.data ? t(key('fenceSaved')) : undefined} />
  </Stack>
}

function Nearby({ session }: { session: Session }) {
  const t = useT()
  const { search, change } = useOperateSearch()
  const criteria = new URLSearchParams(search.q)
  const selectedMode = criteria.get('mode')
  const number = (name: string) => criteria.has(name) ? Number(criteria.get(name)) : undefined
  const params = { lat_micro: number('lat_micro'), lng_micro: number('lng_micro'), kind: criteria.get('kind') ?? undefined,
    n: number('n'), radius_m: number('radius_m'), limit: number('limit') }
  const hasSearch = (selectedMode === 'within' || selectedMode === 'nearest') &&
    Number.isInteger(params.lat_micro) && Number.isInteger(params.lng_micro)
  const [mode, setMode] = useState(selectedMode === 'within' ? 'within' : 'nearest')
  const query = useRuntimeQuery<PlaceHits>(session, selectedMode === 'within' ? '/geo/places/within' : '/geo/places/nearest', params, hasSearch)
  const point = hasSearch ? { lat_micro: params.lat_micro!, lng_micro: params.lng_micro!,
    lat: formatMicro(params.lat_micro!), lng: formatMicro(params.lng_micro!) } : undefined
  const isWithin = mode === 'within'
  return <Panel title={'nearby'}>
    <Pick label={t(key('nearbyQuery'))} value={mode} options={['nearest', 'within'].map(value => ({ value, label: t(key(value)) }))} onChange={setMode} />
    <Form fields={[
      ...pointFields(t, 'nearby', point),
      field(t, 'kind', { value: params.kind, max: 32, validate: noNullIssue }),
      ...(isWithin ? [field(t, 'radius', { value: String(params.radius_m ?? ''), validate: value => wholeIssue(value, 1, defaultRadius) }),
        field(t, 'limit', { value: String(params.limit ?? 50), validate: value => wholeIssue(value, 1, 200) })] :
        [field(t, 'howMany', { value: String(params.n ?? 5), validate: value => wholeIssue(value, 1, 50) })]),
    ]} pending={query.isFetching} submitLabel={t(key('search'))} onSubmit={form => {
      const next = { ...readPoint(form, 'nearby'), kind: optional(form, 'kind'), mode,
        ...(isWithin ? { radius_m: Number(text(form, 'radius')), limit: Number(text(form, 'limit')) } : { n: Number(text(form, 'howMany')) }) }
      const q = new URLSearchParams(Object.entries(next).flatMap(([key, value]) =>
        value === undefined ? [] : [[key, String(value)]])).toString()
      if (search.q === q) void query.refetch()
      else change({ q })
    }} />
    {hasSearch && (query.isPending || query.isError ? <RuntimeState error={query.error} retry={query.refetch} /> :
      query.data.items.length ? <Stack>
        {query.data.truncated && <Alert tone="warning">{t(key('listTruncated'))}</Alert>}
        <Columns label={'nearbyResults'} names={['name', 'kind', 'distanceM']} rows={query.data.items.map(row => ({
          id: row.id, cells: [data(t, row.name), data(t, row.kind), data(t, row.distance_m)],
        }))} />
      </Stack> : <Empty message="noNearby" onAction={query.refetch} />)}
  </Panel>
}

function PointCheck({ session, evaluate = false }: { session: Session; evaluate?: boolean }) {
  const t = useT()
  const write = useRuntimeWrite<{ point: Point; subject_id?: string }, { items: Fence[] } | { inside: string[]; events: FenceEvent[] }>(
    session, evaluate ? '/geo/evaluate' : '/geo/contains', 'POST', evaluate)
  const result = write.data?.data
  return <Panel title={evaluate ? 'evaluatePoint' : 'containsPoint'}>
    <Form fields={[
      ...(evaluate ? [field(t, 'subject_id', { label: 'subject', required: true, max: 128, validate: noNullIssue })] : []),
      ...pointFields(t, 'check'),
    ]} pending={write.isPending} submitLabel={t(key(evaluate ? 'evaluate' : 'checkPoint'))} onSubmit={form =>
      write.mutate({ point: readPoint(form, 'check'), subject_id: evaluate ? text(form, 'subject_id') : undefined })} />
    <WriteStatus error={write.error} reload={write.reset} />
    {result && ('items' in result ? <p>{t(key(result.items.length ? 'insideFences' : 'noContainingFences'), { fences: result.items.map(fence => fence.name).join(', ') })}</p> :
      <Stack><p>{t(key('evaluationSaved'), { count: result.inside.length })}</p>{result.events.length > 0 && <EventTable rows={result.events} />}</Stack>)}
  </Panel>
}

function EventTable({ rows }: { rows: FenceEvent[] }) {
  const t = useT()
  const date = useOperateDate()
  return <Columns label={'fenceEvents'} names={['when', 'subject', 'geofence', 'event', 'lat', 'lng']} rows={rows.map(row => ({
    id: row.id, cells: [date(row.occurred_at), data(t, row.subject_id), data(t, row.geofence_name), enumLabel(t, row.event),
      data(t, formatMicro(row.lat_micro)), data(t, formatMicro(row.lng_micro))],
  }))} />
}

function Events({ session }: { session: Session }) {
  const t = useT()
  const { search, change } = useOperateSearch()
  const page = search.page ?? 1
  const size = 50
  const fences = useRuntimeQuery<Page<Fence>>(session, '/geo/geofences', { limit: 200 })
  const query = useRuntimeQuery<Page<FenceEvent>>(session, '/geo/events', { limit: size, offset: (page - 1) * size,
    subject_id: search.subject, geofence_id: search.fence })
  return <Panel title={'fenceEvents'}>
    <Row><Filter name="subject" max={128} value={search.subject} onChange={subject => change({ subject, page: undefined })} />
      <Pick label={t(key('geofence'))} value={search.fence ?? ''} options={[
        { value: '_none', label: t(key('all')) }, ...(fences.data?.items ?? []).map(f => ({ value: f.id, label: data(t, f.name) })),
      ]} onChange={fence => change({ fence: fence || undefined, page: undefined })} /><Refresh run={query.refetch} /></Row>
    {query.isPending || query.isError ? <RuntimeState error={query.error} retry={query.refetch} /> :
      query.data.items.length ? <EventTable rows={query.data.items} /> : <Empty message="noFenceEvents" onAction={query.refetch} />}
    <Pager label={'fenceEvents'} page={page} size={size} total={query.data?.total ?? 0} change={page => change({ page })} />
  </Panel>
}

function PositionsPanel({ session }: { session: Session }) {
  const t = useT()
  const date = useOperateDate()
  const { search, change } = useOperateSearch()
  const query = useRuntimeQuery<Positions>(session, '/location/positions', { ...world, limit: 100, subject_kind: search.kind })
  const selected = search.subject && !subjectIssue(search.subject) ? search.subject : ''
  const position = useRuntimeQuery<Position>(session, positionPath(selected), {}, !!selected)
  const history = useRuntimeQuery<PositionHistory>(session, `${positionPath(selected)}/history`, { limit: 50 }, !!selected)
  return <Stack>
    <Panel title={'latestPositions'}>
      <Row><Filter name="kind" max={32} value={search.kind} onChange={kind => change({ kind })} /><Refresh run={query.refetch} /></Row>
      {query.isPending || query.isError ? <RuntimeState error={query.error} retry={query.refetch} /> : <>
        {query.data.truncated && <Alert tone="warning">{t(key('listTruncated'))}</Alert>}
        {query.data.items.length ? <Columns label={'latestPositions'} names={['subject', 'kind', 'lat', 'lng', 'updated', 'actions']}
          rows={query.data.items.map(row => ({
            id: row.subject_id, cells: [data(t, row.subject_id), data(t, row.subject_kind), data(t, row.lat), data(t, row.lng),
              data(t, formatAge(ageSeconds(row.updated_at, query.dataUpdatedAt))), <Button onClick={() => change({ subject: row.subject_id })}>{t(key('showHistory'))}</Button>],
          }))} /> : <Empty message="noPositions" onAction={query.refetch} />}
      </>}
    </Panel>
    {selected && <Panel title={'positionHistory'}>
      <Row><Button onClick={() => change({ subject: undefined })}>{t(key('closeHistory'))}</Button></Row>
      {position.isPending || position.isError ? <RuntimeState error={position.error} retry={position.refetch} lines={2} /> :
        <Details values={[
          ['subject', data(t, position.data.subject_id)], ['seq', data(t, position.data.seq)], ['recordedAt', date(position.data.recorded_at)],
          ['lat', data(t, position.data.lat)], ['lng', data(t, position.data.lng)],
        ]} />}
      {history.isPending || history.isError ? <RuntimeState error={history.error} retry={history.refetch} /> : <>
        <p>{t(key('retentionCap'), { count: history.data.retention_cap })}</p>
        {history.data.items.length ? <Columns label={'positionHistory'} names={['seq', 'lat', 'lng', 'recordedAt']} rows={history.data.items.map(row => ({
          id: String(row.seq), cells: [data(t, row.seq), data(t, row.point.lat), data(t, row.point.lng), date(row.recorded_at)],
        }))} /> : <Empty message="noPositionHistory" onAction={history.refetch} />}
      </>}
    </Panel>}
  </Stack>
}
