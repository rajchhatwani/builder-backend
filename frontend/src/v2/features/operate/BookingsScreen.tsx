import { useRef, useState } from 'react'
import { addDays, buildGrid, isActive, isDate, localParts, moveFocus, parseLocalInput, weekInstants, weekRange } from '../../../shell/bookings/calendarLogic'
import type { Cell, Slot } from '../../../shell/bookings/calendarLogic'
import { newIdempotencyKey, toBig } from '../../../shell/money/moneyLogic'
import { useLanguage, useT } from '../../i18n'
import { ConfirmDestructive, Form } from '../../patterns'
import { Alert, Button, Checkbox, Field, Input, Row, Stack } from '../../ui'
import { wholeIssue } from '../../validators/operateRuntime'
import { bookingPath, bookingsPath, resourcePath, resourcesPath } from './api/booking'
import type { Availability, BookingDetail, BookingInput, Capacity, Resource } from './api/booking'
import { useRuntimeWrite } from './api/live'
import type { LiveProps, Page, Session } from './api/live'
import { canWrite } from './api/operate'
import { SectionLink, useOperateSearch } from './components/Common'
import { useMoney } from './components/Money'
import { choices, Columns, data, Details, Empty, enumLabel, field, Filter, key, optional, Pager, Panel, Pick, Refresh,
  RuntimeScreen, RuntimeState, serverFields, text, useRuntimeQuery, WriteStatus } from './components/Runtime'
import './runtime.css'

const pageSize = 50
export default function BookingsScreen(props: LiveProps) {
  return <RuntimeScreen id={props} title={'bookings'}>{session => <Bookings session={session} writable={canWrite(props)} />}</RuntimeScreen>
}
function useZonedDisplay(zone: string) {
  const { language, t } = useLanguage()
  return (value?: string | null) => value ? new Intl.DateTimeFormat(language, {
    timeZone: zone, dateStyle: 'medium', timeStyle: 'short',
  }).format(new Date(value)) : data(t, null)
}
function Bookings({ session, writable }: { session: Session; writable: boolean }) {
  const t = useT()
  const { search, change } = useOperateSearch()
  const page = search.historyPage ?? 1
  const active = search.tab !== 'all' ? search.tab !== 'disabled' : undefined
  const resources = useRuntimeQuery<Page<Resource>>(session, resourcesPath, { limit: 200, kind: search.kind, active, offset: (page - 1) * 200 })
  const rows = resources.data?.items ?? []
  const selected = search.resource ? rows.find(r => r.id === search.resource) : rows[0]
  const resource = useRuntimeQuery<Resource>(session, resourcePath(search.resource ?? ''), {}, !!search.resource && !selected)
  const current = selected ?? resource.data
  return <Stack gap={4}>
    <Row><Refresh run={resources.refetch} /><SectionLink id={session.projectId} section="bookingadmin" label={t(key('bookingadmin'))} /></Row>
    <Panel title={'resources'}>
      <Row><Filter name="kind" max={40} value={search.kind} onChange={kind => change({ kind, resource: undefined, slot: undefined, historyPage: undefined, page: undefined })} />
        <Pick label={t(key('status'))} value={search.tab ?? 'active'} options={choices(t, ['active', 'disabled', 'all']).slice(1)}
          onChange={tab => change({ tab, resource: undefined, slot: undefined, historyPage: undefined, page: undefined })} /></Row>
      {resources.isPending || resources.isError ? <RuntimeState error={resources.error} retry={resources.refetch} /> : rows.length ?
        <Pick label={t(key('resource'))} value={current?.id ?? ''} onChange={resource => change({ resource, page: undefined, slot: undefined, view: undefined })}
          options={rows.map(r => ({ value: r.id, label: t(key('resourceItem'), { name: r.name, kind: r.kind, mode: enumLabel(t, r.mode) }) }))} /> :
        <Empty message="noResources" onAction={resources.refetch} />}
      <Pager label={'resources'} page={page} size={200} total={resources.data?.total ?? 0} change={historyPage => change({ historyPage, resource: undefined, slot: undefined, page: undefined })} />
    </Panel>
    {resource.isError && <RuntimeState error={resource.error} retry={resource.refetch} />}
    {current && <ResourceBookings key={current.id} session={session} resource={current} writable={writable} />}
    {search.view && <BookingDetails key={search.view} session={session} id={search.view} writable={writable} />}
  </Stack>
}

function ResourceBookings({ session, resource, writable }: { session: Session; resource: Resource; writable: boolean }) {
  const { t, language } = useLanguage()
  const { search, change } = useOperateSearch()
  const format = useZonedDisplay(resource.timezone)
  const page = search.page ?? 1
  const today = localParts(Date.now(), resource.timezone).date
  const week = weekRange(search.week && isDate(search.week) ? search.week : today)
  const range = weekInstants(week, resource.timezone)
  const slotMode = resource.mode === 'slot'
  const slots = useRuntimeQuery<Availability>(session, `${resourcePath(resource.id)}/availability`,
    { from: week.from, to: week.to, include_taken: true }, slotMode && resource.active)
  const calendar = useRuntimeQuery<Page<BookingDetail>>(session, bookingsPath, { resource_id: resource.id, ...range, limit: 200 })
  const ledger = useRuntimeQuery<Page<BookingDetail>>(session, bookingsPath, {
    resource_id: resource.id, from: search.from ?? range.from, to: search.until ?? range.to, limit: pageSize, offset: (page - 1) * pageSize, status: search.status,
  })
  const reload = () => Promise.all([calendar.refetch(), ledger.refetch(), ...(slotMode && resource.active ? [slots.refetch()] : [])])
  const dayText = (date: string) => new Intl.DateTimeFormat(language, { timeZone: 'UTC', weekday: 'short', month: 'short', day: 'numeric' }).format(new Date(date + 'T00:00:00Z'))
  const [clock] = useState(() => Date.now())
  const grid = buildGrid(week.days, slots.data?.slots ?? [], calendar.data?.items ?? [], resource.timezone, Math.max(clock, calendar.dataUpdatedAt))
  const selected = grid.cells.flat().find(cell => cell?.key === search.slot)
  const updateWeek = (date?: string) => change({ week: date, page: undefined, slot: undefined })
  const statusOptions = choices(t, ['held', 'confirmed', 'cancelled', 'expired'])
  const localInput = (value?: string) => {
    if (!value || !Number.isFinite(Date.parse(value))) return undefined
    const { date, time } = localParts(value, resource.timezone)
    return date + 'T' + time
  }
  return <Stack gap={4}>
    <Panel title={'resourceDetails'}>
      <Details values={[[ 'name', data(t, resource.name)], ['kind', data(t, resource.kind)], ['mode', enumLabel(t, resource.mode)],
        ['timezone', data(t, resource.timezone)], ['slotMinutes', data(t, resource.slot_minutes)], ['capacity', data(t, resource.capacity)],
        ['minMinutes', data(t, resource.min_minutes)], ['maxMinutes', data(t, resource.max_minutes)],
        ['status', enumLabel(t, resource.active ? 'active' : 'disabled')]]} />
    </Panel>
    <Panel title={'weekCalendar'}>
      <Row><Button onClick={() => updateWeek(addDays(week.from, -7))}>{t(key('previousWeek'))}</Button>
        <Button onClick={() => updateWeek(undefined)}>{t(key('thisWeek'))}</Button>
        <Button onClick={() => updateWeek(addDays(week.from, 7))}>{t(key('nextWeek'))}</Button>
        <Refresh run={reload} />
      </Row>
      <p>{t(key('periodValue'), { start: dayText(week.from), end: dayText(week.to) })}</p>
      {calendar.data && calendar.data.total > calendar.data.items.length && <Alert tone="warning">{t(key('listTruncated'))}</Alert>}
      {slotMode && resource.active && (calendar.isPending || calendar.isError || slots.isPending || slots.isError ?
        <RuntimeState error={calendar.error ?? slots.error} retry={reload} /> : grid.times.length ?
          <WeekGrid grid={grid} dayText={dayText} current={search.slot} onSelect={slot => change({ slot: slot.key })} /> :
          <Empty message="noSlots" onAction={reload} />)}
      {selected && <Stack>
        <p>{t(key('periodValue'), { start: format(selected.startsAt), end: format(selected.endsAt) })}</p>
        {selected.bookings.map(booking => <Row key={booking.id}>
          <span>{t(key('bookingCell'), { status: enumLabel(t, booking.status), name: data(t, booking.customer_ref) })}</span>
          <Button onClick={() => change({ view: booking.id })}>{t(key('open'))}</Button>
        </Row>)}
        {writable && selected.bookable && <BookingForm key={selected.key} session={session} resource={resource}
          slot={{ starts_at: selected.startsAt, ends_at: selected.endsAt, free: true }} onSave={view => change({ view })} />}
      </Stack>}
      {writable && resource.active && !slotMode && <BookingForm session={session} resource={resource} onSave={view => change({ view })} />}
    </Panel>
    <Panel title={'bookingLedger'}>
      <Row><Pick label={t(key('status'))} value={search.status ?? ''} options={statusOptions} onChange={status => change({ status: status || undefined, page: undefined })} />
        <Filter name="fromDate" type="datetime-local" value={localInput(search.from)}
          onChange={value => change({ from: value ? parseLocalInput(value, resource.timezone) ?? undefined : undefined, page: undefined })} />
        <Filter name="toDate" type="datetime-local" value={localInput(search.until)}
          onChange={value => change({ until: value ? parseLocalInput(value, resource.timezone) ?? undefined : undefined, page: undefined })} /></Row>
      {ledger.isPending || ledger.isError ? <RuntimeState error={ledger.error} retry={ledger.refetch} /> : ledger.data.items.length ?
        <Columns label={'bookingLedger'} names={['starts', 'ends', 'status', 'quantity', 'customerRef', 'actions']} rows={ledger.data.items.map(b => ({
          id: b.id, cells: [format(b.starts_at), format(b.ends_at), enumLabel(t, b.status), data(t, b.quantity), data(t, b.customer_ref),
            <Button onClick={() => change({ view: b.id })}>{t(key('open'))}</Button>],
        }))} /> : <Empty message="noBookings" onAction={ledger.refetch} />}
      <Pager label={'bookingLedger'} page={page} size={pageSize} total={ledger.data?.total ?? 0} change={page => change({ page })} />
    </Panel>
  </Stack>
}

function WeekGrid({ grid, dayText, current, onSelect }: { grid: ReturnType<typeof buildGrid>; dayText: (value: string) => string; current?: string; onSelect: (cell: Cell) => void }) {
  const t = useT()
  const refs = useRef<Record<string, HTMLButtonElement | null>>({})
  const [focused, setFocused] = useState<string>()
  const cells = grid.cells.flat()
  const focus = cells.find(cell => cell?.key === (focused ?? current))?.key ?? cells.find(Boolean)?.key
  const exists = grid.cells.map(row => row.map(Boolean))
  return <div className="v2-runtime-calendar">
    <table role="grid" className="v2-runtime-week" aria-label={t(key('weekCalendar'))}>
      <thead><tr><th scope="col">{t(key('time'))}</th>{grid.days.map(day => <th key={day} scope="col">{dayText(day)}</th>)}</tr></thead>
      <tbody>{grid.cells.map((row, r) => <tr key={grid.times[r]}><th scope="row">{data(t, grid.times[r])}</th>
        {row.map((cell, c) => <td key={grid.days[c]}>{cell && <Button
          ref={ref => { refs.current[cell.key] = ref }} tabIndex={focus === cell.key ? 0 : -1} aria-pressed={current === cell.key}
          aria-label={t(key('slotLabel'), { day: dayText(cell.day), time: cell.time, status: enumLabel(t, cell.state) })}
          onFocus={() => setFocused(cell.key)} onClick={() => onSelect(cell)} onKeyDown={event => {
            if (!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
            event.preventDefault()
            const [y, x] = moveFocus(exists, r, c, event.key)
            const next = grid.cells[y]?.[x]
            if (next) refs.current[next.key]?.focus()
          }}>{enumLabel(t, cell.state)}</Button>}</td>)}
      </tr>)}</tbody>
    </table>
    <div className="v2-runtime-days">
      <Stack>{grid.days.map((day, c) => {
        const slots = grid.cells.flatMap(row => row[c] ? [row[c]] : [])
        return slots.length ? <Stack key={day}><h3>{dayText(day)}</h3>
          <Row>{slots.map(slot => <Button key={slot.key} aria-pressed={current === slot.key} onClick={() => onSelect(slot)}>
            {t(key('mobileSlot'), { time: slot.time, status: enumLabel(t, slot.state) })}</Button>)}</Row>
        </Stack> : null
      })}</Stack>
    </div>
  </div>
}

function BookingForm({ session, resource, slot, onSave }: { session: Session; resource: Resource; slot?: Slot; onSave: (id: string) => void }) {
  const t = useT()
  const [requestKey, setRequestKey] = useState(newIdempotencyKey)
  const [capacity, setCapacity] = useState<{ starts_at: string; ends_at: string }>()
  const [rangeError, setRangeError] = useState(false)
  const mutation = useRuntimeWrite<BookingInput, BookingDetail>(session, bookingsPath)
  const check = useRuntimeQuery<Capacity>(session, `${resourcePath(resource.id)}/capacity`, capacity, !!capacity)
  const formRef = useRef<HTMLDivElement>(null)
  const times = (form: FormData) => {
    const starts_at = slot?.starts_at ?? parseLocalInput(text(form, 'starts'), resource.timezone)
    const ends_at = slot?.ends_at ?? parseLocalInput(text(form, 'ends'), resource.timezone)
    return starts_at && ends_at && starts_at < ends_at ? { starts_at, ends_at } : undefined
  }
  return <div ref={formRef}><Stack>
    <Form key={requestKey} fields={[
      ...(!slot ? [field(t, 'starts', { type: 'datetime-local', required: true }), field(t, 'ends', { type: 'datetime-local', required: true,
        validate: (_, form) => times(form) ? undefined : { key: key('timeError') } })] : []),
      ...(resource.mode === 'pool' ? [field(t, 'quantity', { required: true, value: '1', validate: v => wholeIssue(v, 1, resource.capacity) })] : []),
      field(t, 'customerRef', { max: 128 }), field(t, 'notes', { max: 500, area: true }),
      { name: 'confirm', label: t(key('confirmNow')), ownLabel: true,
        control: attrs => <Checkbox {...attrs} label={t(key('confirmNow'))} /> },
    ]} serverErrors={serverFields(mutation.error, { starts_at: 'starts', ends_at: 'ends', customer_ref: 'customerRef' })} actions={resource.mode === 'pool' ? <Button onClick={() => {
      const form = formRef.current?.querySelector('form')
      const window = form && times(new FormData(form))
      setRangeError(!window)
      if (window) {
        if (window.starts_at === capacity?.starts_at && window.ends_at === capacity.ends_at) void check.refetch()
        else setCapacity(window)
      }
    }}>{t(key('checkCapacity'))}</Button> : undefined} formError={rangeError ? t(key('timeError')) : undefined}
    pending={mutation.isPending} submitLabel={t(key(slot ? 'holdSlot' : 'createHold'))} onSubmit={form => {
      const window = times(form)
      if (!window) return
      setRangeError(false)
      mutation.mutate({ ...window, resource_id: resource.id, quantity: resource.mode === 'pool' ? Number(text(form, 'quantity')) : undefined,
        confirm: form.has('confirm'), idempotency_key: requestKey, customer_ref: optional(form, 'customerRef'), notes: optional(form, 'notes') },
      { onSuccess: reply => { onSave(reply.data.id); setRequestKey(newIdempotencyKey()); setCapacity(undefined) } })
    }} />
    {capacity && (check.isPending || check.isError ? <RuntimeState error={check.error} retry={check.refetch} /> :
      <Details values={[[ 'capacity', data(t, check.data.capacity)], ['booked', data(t, check.data.booked)], ['free', data(t, check.data.free)]]} />)}
    <WriteStatus error={mutation.error} reload={mutation.reset} replayed={mutation.data?.replayed}
      success={mutation.data ? t(key(mutation.data.data.status === 'confirmed' ? 'bookingConfirmed' : 'holdCreated')) : undefined} />
  </Stack></div>
}

function BookingDetails({ session, id, writable }: { session: Session; id: string; writable: boolean }) {
  const { change } = useOperateSearch()
  const t = useT()
  const path = bookingPath(id)
  const booking = useRuntimeQuery<BookingDetail>(session, path)
  const resource = useRuntimeQuery<Resource>(session, resourcePath(booking.data?.resource_id ?? ''), {}, !!booking.data)
  return <Panel title={'bookingDetails'}>
    <Row><Button onClick={() => change({ view: undefined })}>{t(key('close'))}</Button></Row>
    {booking.isPending || booking.isError ? <RuntimeState error={booking.error} retry={booking.refetch} /> :
      <BookingRecord session={session} value={booking.data} zone={resource.data?.timezone ?? 'UTC'} writable={writable} reload={booking.refetch} />}
  </Panel>
}
function BookingRecord({ session, value, zone, writable, reload }: { session: Session; value: BookingDetail; zone: string; writable: boolean; reload: () => unknown }) {
  const t = useT()
  const format = useZonedDisplay(zone)
  const money = useMoney()
  const [reason, setReason] = useState('')
  const path = bookingPath(value.id)
  const confirm = useRuntimeWrite<undefined, BookingDetail>(session, `${path}/confirm`)
  const cancel = useRuntimeWrite<{ reason?: string }, BookingDetail>(session, `${path}/cancel`)
  const canAct = writable && isActive(value, Date.now()) && Date.parse(value.starts_at) > Date.now()
  const label = value.status === 'held' ? 'cancelHold' : 'cancelBooking'
  const fee = value.fee_currency && toBig(value.cancel_fee_minor) > 0n ? money(value.cancel_fee_minor ?? 0, value.fee_currency) : undefined
  return <Stack>
    <Details values={[[ 'resource', data(t, value.resource_name)], ['status', enumLabel(t, value.status)], ['starts', format(value.starts_at)],
      ['ends', format(value.ends_at)], ['quantity', data(t, value.quantity)], ['customerRef', data(t, value.customer_ref)],
      ['customerId', data(t, value.customer_id)], ['notes', data(t, value.notes)], ['idempotency', data(t, value.idempotency_key)],
      ['expires', format(value.hold_expires_at)], ['created', format(value.created_at)], ['cancelledAt', format(value.cancelled_at)],
      ['confirmedAt', format(value.confirmed_at)], ['expiredAt', format(value.expired_at)]]} />
    {fee && <Alert tone="info">{t(key('feeRecorded'), { amount: fee })}</Alert>}
    {canAct && <Row>{value.status === 'held' && <Button disabled={confirm.isPending} onClick={() => confirm.mutate(undefined)}>{t(key('confirmBooking'))}</Button>}
      <ConfirmDestructive trigger={<Button variant="danger">{t(key(label))}</Button>} title={t(key(label))}
        description={t(key('cancelBookingHelp'))} action={t(key('cancelBookingYes'))} pending={cancel.isPending}
        onConfirm={async () => { await cancel.mutateAsync({ reason: reason.trim() || undefined }) }}>
        <Field label={t(key('reason'))}>{attrs => <Input {...attrs} value={reason} maxLength={200} onChange={event => setReason(event.target.value)} />}</Field>
      </ConfirmDestructive>
    </Row>}
    <WriteStatus error={cancel.error ?? confirm.error} reload={reload} success={cancel.isSuccess ?
      t(key('bookingCancelled')) : confirm.isSuccess ? t(key('bookingConfirmed')) : undefined} />
  </Stack>
}
