import { useQuery } from '@tanstack/react-query'
import { useReducer, useState } from 'react'
import {
  applyBooking, buildResourceCreate, buildResourceUpdate, describeCancellation, formatSchedule, freeGaps, groupSlots,
  kindToSpec, parseSchedule, rulesFormOf, validateKind, validateRange, validateRules,
} from '../../../shell/bookings/bookingAdminLogic'
import type { KindForm, Obj, RulesForm } from '../../../shell/bookings/bookingAdminLogic'
import { addDays, isActive, isValidTimeZone, localParts, parseLocalInput } from '../../../shell/bookings/calendarLogic'
import type { Mode } from '../../../shell/bookings/calendarLogic'
import { useT } from '../../i18n'
import { ConfirmDestructive, Form } from '../../patterns'
import type { FormField } from '../../patterns'
import { Alert, Button, Checkbox, Row, Stack } from '../../ui'
import { wholeIssue } from '../../validators/operateRuntime'
import { bookingsPath, resourcePath, resourcesPath } from './api/booking'
import type { Availability, BookingDetail, Capacity, Resource } from './api/booking'
import { bookingRulesOptions, useBookingRulesWrite, useRuntimeWrite } from './api/live'
import type { LiveProps, Page, Session } from './api/live'
import { canWrite, fieldErrors } from './api/operate'
import { SectionLink, useOperateDate, useOperateSearch } from './components/Common'
import { choices, Columns, data, Details, Empty, enumLabel, field, Filter, key, Pager, Panel, Pick, Refresh,
  RuntimeScreen, RuntimeState, serverFields, text, useRuntimeQuery, WriteStatus } from './components/Runtime'
import { bookingKinds, initialKinds } from './state/bookingKinds'

const modes = ['slot', 'range', 'pool'] as const
type Translate = ReturnType<typeof useT>
type Packs = { packs: Obj | null; version: number }
type KindFields = Exclude<keyof KindForm, 'mode'>
const messageIssue = (value: string | null | undefined) => value ? { key: key('value'), values: { value } } : undefined
const bookingBlock = (packs?: Obj | null) => packs?.booking as Obj | null | undefined
const kindsOf = (booking?: Obj | null) => Array.isArray(booking?.kinds) ? booking.kinds as Obj[] : []
const checkbox = (t: Translate, name: string, checked: boolean): FormField => ({
  name, label: t(key(name)), ownLabel: true, control: attrs => <Checkbox {...attrs} defaultChecked={checked} label={t(key(name))} />,
})

export default function BookingAdminScreen(props: LiveProps) {
  const rules = useQuery(bookingRulesOptions(props.projectId))
  const packs = rules.data as Packs | undefined
  return <RuntimeScreen id={props} title={'bookingadmin'} builder={<Rules projectId={props.projectId} writable={canWrite(props)} />}>
    {session => <ResourceAdmin session={session} packs={packs?.packs} writable={canWrite(props)} />}
  </RuntimeScreen>
}
function Rules({ projectId, writable }: { projectId: string; writable: boolean }) {
  const t = useT()
  const query = useQuery(bookingRulesOptions(projectId))
  const result = query.data as Packs | undefined
  const [epoch, setEpoch] = useState(0)
  const [saved, setSaved] = useState(false)
  return <Panel title={'rulesKinds'}>
    <p>{t(key('rulesHelp'))}</p>
    {saved && <Alert tone="success">{t(key('rulesSaved'))}</Alert>}
    {query.isError && <RuntimeState error={query.error} retry={query.refetch} />}
    {query.isPending ? <RuntimeState retry={query.refetch} /> : !result ? null :
      !bookingBlock(result.packs) ? <Empty message="noBookingPack" onAction={query.refetch} /> :
        <RulesEditor key={epoch} projectId={projectId} snapshot={result} writable={writable}
          reload={async () => {
            if (!(await query.refetch()).isError) { setSaved(false); setEpoch(v => v + 1) }
          }} onSaved={() => { setSaved(true); setEpoch(v => v + 1) }} />}
    <Row><SectionLink id={projectId} section="bookingsettings" label={t(key('bookingSettings'))} />
      <SectionLink id={projectId} section="see" label={t(key('seePreview'))} /></Row>
  </Panel>
}

const ruleFields = ['read_roles', 'book_roles', 'manage_roles', 'hold_ttl_seconds', 'max_horizon_days', 'free_until_hours', 'fee_minor', 'currency'] as const
const captureRules = (form: FormData) => Object.fromEntries([...ruleFields.map(name => [name, text(form, name)]), ['own_only', form.has('own_only')]]) as unknown as RulesForm
function RulesEditor({ projectId, snapshot, writable, reload, onSaved }: { projectId: string; snapshot: Packs; writable: boolean; reload: () => Promise<void>; onSaved: () => void }) {
  const t = useT()
  const [starting] = useState(snapshot)
  const original = bookingBlock(starting.packs) ?? {}
  const initial = rulesFormOf(original)
  const [kinds, dispatch] = useReducer(bookingKinds, kindsOf(original), initialKinds)
  const [mode, setMode] = useState<Mode>('slot')
  const [summary, setSummary] = useState<string>()
  const mutation = useBookingRulesWrite(projectId)
  const formError = !kinds.items.length ? t(key('kindRequired')) : undefined
  const readKind = (form: FormData, row: typeof kinds.items[number]): KindForm => {
    const read = (name: KindFields) => text(form, name + row.id)
    return { name: row.original ? row.initial.name : read('name'), mode: row.initial.mode, timezone: read('timezone'),
      slot_minutes: read('slot_minutes'), schedule: read('schedule'), capacity: read('capacity'), min_minutes: read('min_minutes'), max_minutes: read('max_minutes') }
  }
  const ruleControls = ruleFields.map(name => field(t, name, {
    value: initial[name], required: !['read_roles', 'book_roles'].includes(name),
    validate: (_, form) => messageIssue(validateRules(captureRules(form))[name]),
  }))
  const kindControls = kinds.items.flatMap((row, index) => {
    const names: KindFields[] = [
      ...(!row.original ? ['name' as const] : []), 'timezone',
      ...(row.initial.mode === 'slot' ? ['slot_minutes', 'schedule'] as const : ['min_minutes', 'max_minutes'] as const),
      ...(row.initial.mode === 'pool' ? ['capacity'] as const : []),
    ]
    return names.map(name => ({
      ...field(t, name, { value: row.initial[name], area: name === 'schedule', max: name === 'name' ? 40 : name === 'timezone' ? 64 : undefined,
        validate: (_, form) => {
          const others = kinds.items.filter(other => other.id !== row.id).map(other => readKind(form, other).name)
          return messageIssue(validateKind(readKind(form, row), index, others)[`kinds[${index}].${name}`])
        } }),
      name: name + row.id, kindId: row.id,
    }))
  })
  const errors = Object.fromEntries(Object.entries(fieldErrors(mutation.error, 'packs.booking')).flatMap(([path, messages]) => {
    const kindPath = /^kinds(?:\[(\d+)\]|\.(\d+))\.(\w+)$/.exec(path)
    const name = kindPath ? kindPath[3] + (kinds.items[Number(kindPath[1] ?? kindPath[2])]?.id ?? '') : path.replace(/^cancellation\./, '')
    const issue = messageIssue(messages.join(' '))
    return issue ? [[name, issue]] : []
  }))
  return <Stack>
    <div onChange={event => {
      const form = (event.target as HTMLElement).closest('form')
      if (!form) return
      const rules = captureRules(new FormData(form))
      setSummary(describeCancellation(rules.free_until_hours, rules.fee_minor, rules.currency))
    }}>
      <Form fields={[...ruleControls, checkbox(t, 'own_only', initial.own_only), ...kindControls]} serverErrors={errors}
        pending={mutation.isPending} readOnly={!writable} submitProps={{ hidden: !writable, disabled: !kinds.items.length }} formError={formError}
        submitLabel={t(key('saveRules'))} layout={controls => <Stack>
          {ruleControls.map(f => controls[f.name])}{controls.own_only}
          <p>{data(t, summary ?? describeCancellation(initial.free_until_hours, initial.fee_minor, initial.currency))}</p>
          {kinds.items.map(row => <fieldset key={row.id}><legend>{t(key('kindLegend'), { name: row.initial.name || enumLabel(t, row.initial.mode) })}</legend>
            <Stack>{kindControls.filter(f => f.kindId === row.id).map(f => controls[f.name])}
              {writable && <Row><ConfirmDestructive trigger={<Button variant="danger" disabled={mutation.isPending}>{t(key('removeKind'))}</Button>}
                title={t(key('removeKind'))} description={t(key('removeKindHelp'))} action={t(key('removeKind'))}
                onConfirm={() => { dispatch({ type: 'remove', id: row.id }) }} /></Row>}</Stack>
          </fieldset>)}
        </Stack>} onSubmit={form => {
          mutation.mutate({ packs: applyBooking(starting.packs, captureRules(form), kinds.items.map(row => kindToSpec(readKind(form, row), row.original))), version: starting.version },
            { onSuccess: onSaved })
        }} />
    </div>
    {writable && <Row>
      <Pick label={t(key('newKindMode'))} value={mode} options={choices(t, modes).slice(1)} onChange={value => setMode(modes.find(mode => mode === value) ?? 'slot')} />
      <Button disabled={mutation.isPending || kinds.items.length >= 20} onClick={() => { dispatch({ type: 'add', mode }) }}>{t(key('addKind'))}</Button>
    </Row>}
    <WriteStatus error={mutation.error} reload={reload} />
  </Stack>
}

function ResourceAdmin({ session, packs, writable }: { session: Session; packs?: Obj | null; writable: boolean }) {
  const t = useT()
  const { search, change } = useOperateSearch()
  const date = useOperateDate()
  const page = search.page ?? 1
  const resources = useRuntimeQuery<Page<Resource>>(session, resourcesPath, { limit: 200, offset: (page - 1) * 200, kind: search.kind,
    active: search.status === 'active' ? true : search.status === 'disabled' ? false : undefined })
  const edit = useRuntimeQuery<Resource>(session, resourcePath(search.edit ?? ''), {}, Boolean(search.edit))
  const [create, setCreate] = useState(false)
  const kinds = kindsOf(bookingBlock(packs))
  const list = resources.data?.items ?? []
  const allKinds = new Map<string, Mode>()
  for (const row of list) allKinds.set(row.kind, row.mode)
  for (const k of kinds) if (typeof k.name === 'string' && modes.includes(k.mode as Mode)) allKinds.set(k.name, k.mode as Mode)
  return <Stack gap={4}>
    <Row><Refresh run={resources.refetch} /><SectionLink id={session.projectId} section="bookings" label={t(key('bookings'))} />
      {writable && <Button onClick={() => setCreate(!create)}>{t(key(create ? 'close' : 'createResource'))}</Button>}</Row>
    <Panel title={'resources'}>
      <Row><Filter name="kind" max={40} value={search.kind} onChange={kind => change({ kind, page: undefined })} />
        <Pick label={t(key('status'))} value={search.status ?? ''} options={choices(t, ['active', 'disabled'])}
          onChange={status => change({ status: status || undefined, page: undefined })} /></Row>
      {resources.isPending || resources.isError ? <RuntimeState error={resources.error} retry={resources.refetch} /> :
        list.length ? <Columns label={'resources'} names={['name', 'kind', 'mode', 'timezone', 'status', 'created', 'actions']} rows={list.map(row => ({
          id: row.id, cells: [data(t, row.name), data(t, row.kind), enumLabel(t, row.mode), data(t, row.timezone), enumLabel(t, row.active ? 'active' : 'disabled'),
            date(row.created_at), <Row><Button onClick={() => change({ edit: row.id })}>{t(key('open'))}</Button>
              {writable && <ToggleResource session={session} row={row} reload={resources.refetch} />}</Row>],
        }))} /> : <Empty message="noResources" action={writable ? 'createResource' : undefined} onAction={writable ? () => setCreate(true) : resources.refetch} />}
      <Pager label={'resources'} size={200} page={page} total={resources.data?.total ?? 0} change={page => change({ page })} />
    </Panel>
    {search.edit && <Panel title={'resourceDetails'}>
      <Row><Button onClick={() => change({ edit: undefined })}>{t(key('close'))}</Button></Row>
      {edit.isPending || edit.isError ? <RuntimeState error={edit.error} retry={edit.refetch} /> : <Stack>
        <Details values={[[ 'name', data(t, edit.data.name)], ['resourceId', data(t, edit.data.id)], ['mode', enumLabel(t, edit.data.mode)],
          ['slotMinutes', data(t, edit.data.slot_minutes)], ['capacity', data(t, edit.data.capacity)], ['minMinutes', data(t, edit.data.min_minutes)],
          ['maxMinutes', data(t, edit.data.max_minutes)], ['schedule', data(t, formatSchedule(edit.data.schedule))]]} />
        {writable && <ResourceEditor key={edit.data.id} session={session} kinds={allKinds} row={edit.data} />}
      </Stack>}
    </Panel>}
    {writable && create && <Panel title={'createResource'}>
      {allKinds.size ? <ResourceEditor session={session} kinds={allKinds} /> : <p>{t(key('kindRequired'))}</p>}
    </Panel>}
    <Panel title={'availability'}>
      {resources.isPending || resources.isError ? <RuntimeState error={resources.error} retry={resources.refetch} /> :
        <AvailabilityCheck session={session} rows={list.filter(row => row.active)} />}
    </Panel>
    {writable && <Expire session={session} reload={resources.refetch} />}
  </Stack>
}
function ResourceEditor({ session, kinds, row }: { session: Session; kinds: Map<string, Mode>; row?: Resource }) {
  const t = useT()
  const [kind, setKind] = useState('')
  const [error, setError] = useState('')
  const [epoch, setEpoch] = useState(0)
  const mode = row?.mode ?? kinds.get(kind)
  const mutation = useRuntimeWrite<Obj, Resource>(session, row ? resourcePath(row.id) : resourcesPath, row ? 'PATCH' : 'POST')
  return <Stack>
    {!row && <Pick label={t(key('kind'))} value={kind} options={choices(t, [...kinds.keys()], 'choose')} onChange={setKind} />}
    {(row || mode) && <Form key={kind + ':' + epoch} fields={[
      field(t, 'name', { value: row?.name, max: 120, required: true }),
      field(t, 'timezone', { value: row?.timezone, max: 64, required: !!row, validate: value => value && !isValidTimeZone(value.trim()) ? { key: key('timezoneError') } : undefined }),
      ...(mode === 'pool' && !row ? [field(t, 'capacity', { validate: value => value ? wholeIssue(value, 1, 100_000) : undefined })] : []),
      ...(mode === 'slot' ? [field(t, 'schedule', { value: formatSchedule(row?.schedule), area: true,
        validate: value => messageIssue(parseSchedule(value, row?.slot_minutes).error) })] : []),
      ...(!row ? [checkbox(t, 'active', true)] : []),
    ]} serverErrors={serverFields(mutation.error, {}, path => path.startsWith('schedule') ? 'schedule' : undefined)} formError={error || undefined} pending={mutation.isPending} submitLabel={t(key(row ? 'save' : 'createResource'))} onSubmit={form => {
      const draft = { kind, name: text(form, 'name'), timezone: text(form, 'timezone'), capacity: text(form, 'capacity'),
        schedule: text(form, 'schedule'), active: row?.active ?? form.has('active') }
      const result = row ? buildResourceUpdate(row, draft) : buildResourceCreate(draft, mode ?? null)
      setError(result.error ? data(t, result.error) : '')
      if (result.body) mutation.mutate(result.body, { onSuccess: () => setEpoch(v => v + 1) })
    }} />}
    <WriteStatus error={mutation.error} reload={mutation.reset} success={mutation.data ? t(key(row ? 'resourceSaved' : 'resourceCreated'), { name: mutation.data.data.name }) : undefined} />
  </Stack>
}
function ToggleResource({ session, row, reload }: { session: Session; row: Resource; reload: () => unknown }) {
  const t = useT()
  const mutation = useRuntimeWrite<{ active: boolean }, Resource>(session, resourcePath(row.id), 'PATCH')
  return <Stack>
    {row.active ? <ConfirmDestructive trigger={<Button variant="danger">{t(key('disable'))}</Button>} title={t(key('disableNamed'), { name: row.name })}
      description={t(key('disableHelp'))} action={t(key('disableYes'))} pending={mutation.isPending}
      onConfirm={async () => { await mutation.mutateAsync({ active: false }) }} /> :
      <Button disabled={mutation.isPending} onClick={() => mutation.mutate({ active: true })}>{t(key('enable'))}</Button>}
    <WriteStatus error={mutation.error} reload={reload} />
  </Stack>
}

function AvailabilityCheck({ session, rows }: { session: Session; rows: Resource[] }) {
  const t = useT()
  const date = useOperateDate()
  const { search, change } = useOperateSearch()
  const selected = rows.find(r => r.id === search.resource) ?? rows[0]
  const selectedWindow = search.resource === selected?.id && search.from && search.until ? { from: search.from, to: search.until } : undefined
  const path = resourcePath(selected?.id ?? '')
  const slots = useRuntimeQuery<Availability>(session, `${path}/availability`, { ...selectedWindow, include_taken: true }, !!selectedWindow && selected?.mode === 'slot')
  const capacity = useRuntimeQuery<Capacity>(session, `${path}/capacity`, { starts_at: selectedWindow?.from, ends_at: selectedWindow?.to }, !!selectedWindow && selected?.mode === 'pool')
  const bookings = useRuntimeQuery<Page<BookingDetail>>(session, bookingsPath, { ...selectedWindow, resource_id: selected?.id, limit: 200 }, !!selectedWindow && selected?.mode === 'range')
  if (!selected) return <p>{t(key('noAvailabilityResources'))}</p>
  const slotMode = selected.mode === 'slot'
  const today = localParts(Date.now(), selected.timezone).date
  const selectedQuery = slotMode ? slots : selected.mode === 'pool' ? capacity : bookings
  const parse = (form: FormData) => {
    const from = text(form, 'starts')
    const to = text(form, 'ends')
    if (slotMode) return { from, to, error: validateRange(from, to) }
    const start = parseLocalInput(from, selected.timezone)
    const end = parseLocalInput(to, selected.timezone)
    return { from: start ?? '', to: end ?? '', error: !start || !end || start >= end ? t(key('timeError')) : null }
  }
  return <Stack>
    <Pick label={t(key('resource'))} value={selected.id} options={rows.map(item => ({ value: item.id, label: data(t, item.name) }))}
      onChange={resource => change({ resource, from: undefined, until: undefined })} />
    <p>{t(key('inTimezone'), { timezone: selected.timezone })}</p>
    <Form key={selected.id} fields={[
      field(t, 'starts', { label: slotMode ? 'fromDate' : 'starts', type: slotMode ? 'date' : 'datetime-local', required: true, value: slotMode ? today : undefined }),
      field(t, 'ends', { label: slotMode ? 'toDate' : 'ends', type: slotMode ? 'date' : 'datetime-local', required: true,
        value: slotMode ? addDays(today, 6) : undefined, validate: (_, form) => messageIssue(parse(form).error) }),
    ]} pending={!!selectedWindow && selectedQuery.isFetching} submitLabel={t(key(selected.mode === 'pool' ? 'checkCapacity' : 'checkAvailability'))} onSubmit={form => {
      const { from, to } = parse(form)
      if (selectedWindow?.from === from && selectedWindow.to === to) void selectedQuery.refetch()
      else change({ resource: selected.id, from, until: to })
    }} />
    {selectedWindow && (selectedQuery.isPending || selectedQuery.isError ?
      <RuntimeState error={selectedQuery.error} retry={selectedQuery.refetch} /> : <>
        {slotMode && slots.data && (slots.data.slots.length ? <Columns label={'availability'} names={['date', 'free', 'taken']} rows={groupSlots(slots.data.slots, selected.timezone).map(d => ({
          id: d.day, cells: [data(t, d.day), data(t, d.free.join(', ')), data(t, d.taken.join(', '))],
        }))} /> : <Empty message="noSlots" onAction={slots.refetch} />)}
        {selected.mode === 'pool' && capacity.data && <Details values={[[ 'capacity', data(t, capacity.data.capacity)],
          ['booked', data(t, capacity.data.booked)], ['free', data(t, capacity.data.free)]]} />}
        {selected.mode === 'range' && bookings.data && (bookings.data.total > bookings.data.items.length ?
          <Alert tone="warning">{t(key('listTruncated'))}</Alert> : <Columns label={'availability'} names={['starts', 'ends']}
            rows={freeGaps(bookings.data.items.filter(b => isActive(b, bookings.dataUpdatedAt)), Date.parse(selectedWindow.from), Date.parse(selectedWindow.to))
              .map(gap => ({ id: gap.from, cells: [date(gap.from), date(gap.to)] }))} />)}
      </>)}
  </Stack>
}
function Expire({ session, reload }: { session: Session; reload: () => unknown }) {
  const t = useT()
  const mutation = useRuntimeWrite<undefined, { expired: number }>(session, '/booking/expire')
  return <Panel title={'expireHolds'}>
    <Row><ConfirmDestructive trigger={<Button variant="danger">{t(key('expireHolds'))}</Button>} title={t(key('expireHolds'))}
      description={t(key('expireHelp'))} action={t(key('expireHolds'))} pending={mutation.isPending}
      onConfirm={async () => { await mutation.mutateAsync(undefined) }} /></Row>
    <WriteStatus error={mutation.error} reload={reload} success={mutation.data ? t(key('expiredHolds'), { count: mutation.data.data.expired }) : undefined} />
  </Panel>
}
