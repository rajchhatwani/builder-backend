import { useRef, useState } from 'react'
import { useT } from '../../i18n'
import { Form } from '../../patterns'
import { Alert, Grid, Input, Stack } from '../../ui'
import { departureIssue, noNullIssue } from '../../validators/operateRuntime'
import { formatDistance, formatDuration } from '../../../shell/operations/opsLogic'
import { useRuntimeWrite } from './api/live'
import type { LiveProps, Page, Session } from './api/live'
import type { Coordinates, Geocode, Place, Positions, RouteBody, RouteMode, RouteResult } from './api/tools'
import { useOperateDate } from './components/Common'
import { data, Details, Empty, enumLabel, field, key, Panel, Pick, RuntimeState, selectField, serverFields, text, useRuntimeQuery, WriteStatus } from './components/Runtime'
import { pointFields, PointGroup, readPoint, ToolsLinks, world } from './components/RuntimeTools'
import { CoordinatePlot } from './components/CoordinatePlot'
import { ToolScreen } from './components/ToolScreen'

const modes = ['drive', 'walk', 'bike'] as const
const services = ['route', 'eta', 'distance'] as const
type Service = typeof services[number]
type Choice = { value: string; label: string; point: Coordinates }

export default function RoutingScreen(props: LiveProps) {
  return <ToolScreen id={props} title={'routing'}>{session => <Routing session={session} />}</ToolScreen>
}

function Routing({ session }: { session: Session }) {
  const t = useT()
  const lookup = useRuntimeWrite<{ address: string }, Geocode>(session, '/geo/geocode', 'POST', false)
  const places = useRuntimeQuery<Page<Place>>(session, '/geo/places', { limit: 200 })
  const positions = useRuntimeQuery<Positions>(session, '/location/positions', { ...world, limit: 100 })
  const address = useRef<HTMLInputElement>(null)
  const result = lookup.data?.data
  const choices: Choice[] = [
    ...(result ? [{ value: 'address', label: t(key('geocodedAddress')), point: result }] : []),
    ...(places.data?.items ?? []).map(point => ({ value: 'place:' + point.id, label: data(t, point.name), point })),
    ...(positions.data?.items ?? []).map(point => ({ value: 'subject:' + point.subject_id, label: data(t, point.subject_id), point })),
  ]
  return <Stack gap={4}>
    <ToolsLinks session={session} sections={['geosettings', 'places']} />
    <Panel title={'geocode'}>
      <Form fields={[{ ...field(t, 'address', { required: true, max: 300, validate: noNullIssue }), control: attrs => <Input {...attrs} ref={address} maxLength={300} /> }]}
        submitLabel={t(key('geocodeRun'))} serverErrors={serverFields(lookup.error)} pending={lookup.isPending}
        onSubmit={form => lookup.mutate({ address: text(form, 'address') })} />
      {lookup.isPending ? <RuntimeState retry={lookup.reset} lines={3} /> :
        lookup.isError ? <RuntimeState error={lookup.error} retry={() => lookup.variables && lookup.mutate(lookup.variables)} /> :
        result ? <Details values={[
          ['address', data(t, lookup.variables?.address)], ['lat', data(t, result.lat)], ['lng', data(t, result.lng)],
          ['microLat', data(t, result.lat_micro)], ['microLng', data(t, result.lng)], ['provider', data(t, result.provider)],
        ]} /> : <Empty message="noGeocode" action="geocodeRun" onAction={() => address.current?.focus()} />}
    </Panel>
    {services.map(service => <RouteForm key={service} service={service} session={session} choices={choices} />)}
  </Stack>
}

function RouteForm({ service, session, choices }: { service: Service; session: Session; choices: Choice[] }) {
  const t = useT()
  const date = useOperateDate()
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const request = useRuntimeWrite<RouteBody, RouteResult>(session, `/geo/${service}`, 'POST', false)
  const origin = service === 'distance' ? 'pointA' : 'origin'
  const destination = service === 'distance' ? 'pointB' : 'destination'
  const options = [{ value: '_none', label: t(key('enterCoordinates')) }, ...choices]
  const fields = [
    ...pointFields(t, 'a', choices.find(item => item.value === start)?.point),
    ...pointFields(t, 'b', choices.find(item => item.value === end)?.point),
    ...(service === 'distance' ? [] : [selectField(t, 'mode', modes.map(value => ({ value, label: enumLabel(t, value) })), 'drive')]),
    ...(service === 'eta' ? [field(t, 'departure', { type: 'datetime-local', validate: departureIssue })] : []),
  ]
  const result = request.data?.data
  const submitted = request.variables
  const plotted = submitted ? 'a' in submitted ? [submitted.a, submitted.b] : [submitted.origin, submitted.destination] : []
  const departure = result?.arrives_at && result.duration_s !== undefined ?
    Date.parse(result.arrives_at) - result.duration_s * 1000 : undefined
  return <Panel title={service}>
    {choices.length > 0 && <Grid>
      <Pick label={t(key(origin + 'Source'))} value={start} options={options} onChange={setStart} />
      <Pick label={t(key(destination + 'Source'))} value={end} options={options} onChange={setEnd} />
    </Grid>}
    <Form fields={fields} pending={request.isPending} submitLabel={t(key(service + 'Run'))} serverErrors={serverFields(request.error, { depart_at: 'departure' })}
      layout={controls => <Stack><Grid>
        <PointGroup label={origin}><div key={start}><Stack>{controls.alat}{controls.alng}</Stack></div></PointGroup>
        <PointGroup label={destination}><div key={end}><Stack>{controls.blat}{controls.blng}</Stack></div></PointGroup>
      </Grid>{controls.mode}{controls.departure}</Stack>}
      onSubmit={form => {
        const a = readPoint(form, 'a'), b = readPoint(form, 'b')
        const local = text(form, 'departure')
        request.mutate(service === 'distance' ? { a, b } :
          { origin: a, destination: b, mode: text(form, 'mode') as RouteMode, depart_at: local ? new Date(local).toISOString() : undefined })
      }} />
    <WriteStatus error={request.error} reload={request.reset} />
    {result && <Stack>
      <Alert tone="success">{t(key('routingResult'))}</Alert>
      <Details values={[
        ['distance', t(key('distanceResult'), { distance: formatDistance(result.distance_m), metres: result.distance_m })],
        ...(result.duration_s === undefined ? [] : [['duration', data(t, formatDuration(result.duration_s))]] as [string, string][]),
        ...(submitted && 'mode' in submitted ? [['mode', enumLabel(t, result.mode ?? submitted.mode)]] as [string, string][] : []),
        ...(result.provider ? [['provider', data(t, result.provider)]] as [string, string][] : []),
        ...(departure === undefined ? [] : [['departureUsed', date(departure)], ['arrival', date(result.arrives_at)]] as [string, string][]),
      ]} />
      <CoordinatePlot label={'directLine'} segment points={plotted.map((point, index) => ({ id: String(index), point, name: t(key(index ? destination : origin)) }))} />
    </Stack>}
  </Panel>
}
