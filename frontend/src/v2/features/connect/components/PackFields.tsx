import { useState } from 'react'
import type { ReactNode } from 'react'
import { useNavigate, useSearch } from '@tanstack/react-router'
import type { Path } from '../../../../forms/schemaLogic'
import type { JsonSchema, PathErrors } from '../../../../forms/types'
import { useT } from '../../../i18n'
import { ConfirmDestructive } from '../../../patterns'
import { SchemaFields } from '../../../patterns/SchemaFields'
import type { SchemaFieldOverride } from '../../../patterns/SchemaFields'
import { Alert, Button, Card, Checkbox, Disclosure, Field, Grid, Input, Row, Select, Stack, Table, Textarea } from '../../../ui'
import { bookingWeekdays, isBookingSchedule, packCurrencyExponents, packRanges } from '../../../validators'
import type { BookingSchedule } from '../../../validators'
import type { PackBlock } from '../api/packs'
import { changeBookingMode } from '../state/packs'
import type { PackDefinition } from '../state/packs'

type Role = { name: string; label: string }
type Props = {
  definition: PackDefinition; value: PackBlock; readOnly: boolean; errors: PathErrors; roles: Role[]
  ceiling: number; revision: number; onChange: (path: Path, value: unknown) => void
  onBlur: (path: string) => void; onStructure: (path: string) => void
}
type Control = SchemaFieldOverride & { onBlur: () => void }
const codes = Object.keys(packCurrencyExponents).sort()
const timezones = ['UTC', ...(Intl.supportedValuesOf?.('timeZone') ?? [])]
const timePattern = '\\d{2}:\\d{2}'
const integerFields = new Set(Object.values(packRanges).flatMap(Object.keys))

const fieldHelp = new Set(['rounding', 'rates_bp', 'max_amount_minor', 'max_entries', 'max_lines', 'number_prefix',
  'payment_terms_days', 'aging_buckets_days', 'commission_bp', 'timezone', 'mode', 'name', 'slot_minutes',
  'min_minutes', 'max_minutes', 'hold_ttl_seconds', 'max_horizon_days', 'free_until_hours', 'fee_minor',
  'currency', 'own_only', 'grid_cell_micro', 'max_radius_m', 'history_cap', 'max_subjects'])

function localize(schema: JsonSchema, t: ReturnType<typeof useT>, ceiling: number, name = ''): JsonSchema {
  return {
    ...schema,
    'x-ui': {
      ...schema['x-ui'],
      ...(name ? { label: t('connectC.field.' + name) } : {}),
      ...(schema['x-ui']?.itemLabel ? { itemLabel: t('connectC.field.kind') } : {}),
      ...(fieldHelp.has(name) || name === 'tolerance_minor' ? { help: t('connectC.help.' + name, { ceiling }) } : {}),
    },
    ...(schema.properties && { properties: Object.fromEntries(Object.entries(schema.properties)
      .map(([key, child]) => [key, localize(child, t, ceiling, key)])) }),
    ...(schema.items && { items: localize(schema.items, t, ceiling) }),
    ...(schema.anyOf && { anyOf: schema.anyOf.map(child => localize(child, t, ceiling)) }),
  }
}

export function PackFields({ definition, value, readOnly, errors, roles, ceiling, revision, onChange, onBlur, onStructure }: Props) {
  const t = useT()
  const selected = useSearch({ strict: false, select: search => search.bookingKind })
  const navigate = useNavigate({ from: '/projects/$projectId/$section' })
  const selectKind = (bookingKind?: number) => { void navigate({ search: previous => ({ ...previous, bookingKind }), replace: true }) }
  function override(props: SchemaFieldOverride) {
    const { path, value: current, id, error } = props
    const name = String(path.at(-1))
    const blur = () => onBlur(path.join('.'))
    const control = { ...props, onBlur: blur }
    if (definition.roles?.includes(name)) return <RoleChoices {...control} name={name} roles={roles} />
    if (name === 'currencies') return <Currencies {...control} />
    if (name === 'schedule') return <Schedule {...control} error={[error, ...Object.entries(errors).filter(([key]) =>
      key.startsWith(path.join('.') + '.')).flatMap(([, messages]) => messages)].filter(Boolean).join(' ')} />
    if (name === 'mode') return <Field id={id} label={t('connectC.field.mode')} hint={t('connectC.help.mode')} error={error}>
      {attrs => <Select options={['slot', 'range', 'pool'].map(mode => ({ value: mode, label: t('connectC.mode.' + mode) }))}
        value={String(current)} disabled={readOnly} triggerProps={attrs} onValueChange={mode => {
          const index = Number(path[1])
          const kinds = value.kinds as PackBlock[]
          const parent = path.slice(0, -1)
          onStructure(parent.join('.'))
          onChange(parent, changeBookingMode(kinds[index], mode))
        }} />}
    </Field>
    if (name === 'aging_buckets_days') return <AgingDays {...control} />
    if (integerFields.has(name)) return <Field id={id} label={t('connectC.field.' + name)} error={error}
      hint={fieldHelp.has(name) || name === 'tolerance_minor' ? t('connectC.help.' + name, { ceiling }) : undefined}>
      {attrs => <Input {...attrs} type="number" step={1} value={typeof current === 'number' || typeof current === 'string' ? current : ''}
        readOnly={readOnly} onBlur={blur} onChange={event => {
          const input = event.target.value
          props.onChange(/^-?\d+$/.test(input) ? Number(input) : input)
        }} />}
    </Field>
    if (name === 'timezone') return <Field id={id} label={t('connectC.field.timezone')} hint={t('connectC.help.timezone')} error={error}>
      {attrs => <><Input {...attrs} value={String(current ?? '')} readOnly={readOnly} list={id + '-zones'}
        onBlur={blur} onChange={event => props.onChange(event.target.value)} />
        <datalist id={id + '-zones'}>{timezones.map(zone => <option key={zone} value={zone} />)}</datalist></>}
    </Field>
  }
  return <Stack>
    {Object.entries(definition.groups).map(([group, schema]) => {
      const nested = group === 'tax' || group === 'payouts' || group === 'cancellation' || group === 'kinds'
      const fields = <SchemaFields key={revision} schema={localize(schema, t, ceiling)} value={value} onChange={onChange} errors={errors}
        onBlur={onBlur} onStructure={onStructure} readOnly={readOnly} fieldOverride={override} confirmRemove groupHeadings
        optionalLabel={label => t('connectC.enable', { label })}
        rowDetail={(path, item) => {
          if (path.join('.') !== 'kinds') return
          const kind = item as PackBlock
          return <p className="v2-muted">{t('connectC.kindSummary', {
            mode: t('connectC.mode.' + String(kind.mode)), timezone: String(kind.timezone ?? ''),
          })}</p>
        }}
        selectedRow={path => path.join('.') === 'kinds' ? { index: selected, select: selectKind } : undefined} />
      if (nested) return <div key={group}>{fields}</div>
      return <Card key={group}><Stack>
        <h2>{t('connectC.group.' + group)}</h2>
        {group === 'accounts' && <p>{t('connectC.accountsHelp')}</p>}
        {group === 'matching' && <p>{t('connectC.matchingHelp')}</p>}
        {group === 'index' && <p>{t('connectC.indexHelp')}</p>}
        {group === 'retention' && <p>{t('connectC.retentionHelp')}</p>}
        {fields}
      </Stack></Card>
    })}
  </Stack>
}

function RoleChoices({ id, name, value, roles, readOnly, error, onChange, onBlur }: Control & { name: string; roles: Role[] }) {
  const t = useT()
  const chosen = Array.isArray(value) ? value as string[] : []
  const choices = new Map(roles.map(role => [role.name, role.label || role.name]))
  for (const role of chosen) if (!choices.has(role)) choices.set(role, role)
  return <fieldset className="v2-pack-fieldset" aria-describedby={id + '-help'}>
    <legend>{t('connectC.field.' + name)}</legend>
    <Stack gap={1}>
      <Row>{Array.from(choices, ([role, label]) => <Checkbox key={role} label={t('schema.option', { value: label })}
        checked={chosen.includes(role)} disabled={readOnly} onBlur={onBlur} aria-invalid={error ? true : undefined}
        onChange={event => onChange(event.target.checked ? [...chosen, role] : chosen.filter(name => name !== role))} />)}</Row>
      <p id={id + '-help'} className="v2-muted">{t(name === 'manage_roles' ? 'connectC.manageHelp' : 'connectC.roleHelp')}</p>
      {error && <Alert tone="danger">{t('common.serverText', { text: error })}</Alert>}
    </Stack>
  </fieldset>
}

function Currencies({ id, value, readOnly, error, onChange, onBlur }: Control) {
  const t = useT()
  const current = Array.isArray(value) ? value as string[] : []
  const choices = codes.filter(code => !current.includes(code))
  const [draft, choose] = useState('')
  const next = choices.includes(draft) ? draft : choices[0]
  const columns = ['code', 'decimals', ...(!readOnly ? ['actions'] : [])].map(id => ({ id, label: t('connectC.column.' + id) }))
  return <Stack>
    {current.length ? <Table label={t('connectC.accepted')} columns={columns} rows={current.map((code, index) => ({
      id: String(index), cells: [
        t('schema.option', { value: code }),
        Object.hasOwn(packCurrencyExponents, code) ? t('connectC.value', { value: packCurrencyExponents[code] }) : t('connectC.unsupported'),
        !readOnly && <ConfirmDestructive trigger={<Button variant="danger" aria-label={t('connectC.removeCurrency', { code })}>{t('schema.remove')}</Button>}
          title={t('connectC.removeCurrency', { code })} description={t('connectC.removeCurrencyHelp')} action={t('schema.remove')}
          onConfirm={() => { onChange(current.filter((_, position) => position !== index)); onBlur() }} />,
      ],
    }))} /> : <p>{t('connectC.chooseCurrency')}</p>}
    {!readOnly && <Row>
      <Field id={id} label={t('connectC.column.code')} error={error}>{attrs => <Select options={choices.map(value => ({
        value, label: t('schema.option', { value }),
      }))} value={next ?? ''} disabled={!next || current.length >= 50} triggerProps={attrs} onValueChange={choose} />}</Field>
      <Button disabled={!next || current.length >= 50} onClick={() => onChange([...current, next])}>{t('connectC.addCurrency')}</Button>
    </Row>}
    {readOnly && error && <Alert tone="danger">{t('common.serverText', { text: error })}</Alert>}
  </Stack>
}

function AgingDays({ id, value, readOnly, error, onChange, onBlur }: Control) {
  const t = useT()
  const [raw, setRaw] = useState<string>()
  return <Field id={id} label={t('connectC.field.aging_buckets_days')} hint={t('connectC.help.aging_buckets_days')} error={error}>
    {attrs => <Input {...attrs} readOnly={readOnly} value={raw ?? (Array.isArray(value) ? value.join(', ') : '')}
      onBlur={() => { setRaw(undefined); onBlur() }} onChange={event => {
        const text = event.target.value
        setRaw(text)
        onChange(text.split(',').map(part => part.trim()).filter(Boolean).map(part => /^\d+$/.test(part) ? Number(part) : part))
      }} />}
  </Field>
}

function Schedule({ id, value, readOnly, error, onChange, onBlur }: Control) {
  const t = useT()
  const [json, setJson] = useState(false)
  const [raw, setRaw] = useState<string>()
  const structured = isBookingSchedule(value)
  const useJson = json || !structured
  const schedule: BookingSchedule = structured ? value : {}
  function editDay(day: string, windows: BookingSchedule[string]) {
    const { [day]: _removed, ...rest } = schedule
    onChange(windows.length ? { ...rest, [day]: windows } : rest)
  }
  return <fieldset className="v2-pack-fieldset"><legend>{t('connectC.field.schedule')}</legend><Stack>
    <Row><Button disabled={!structured} aria-invalid={error && !useJson ? true : undefined} aria-pressed={useJson}
      onClick={() => { setRaw(undefined); setJson(!useJson) }}>{t(useJson ? 'connectC.openingWindows' : 'connectC.editJson')}</Button></Row>
    {useJson ? <Field id={id} label={t('connectC.field.schedule')} error={error} hint={t('connectC.help.schedule')}>
      {attrs => <Textarea {...attrs} rows={5} readOnly={readOnly} onBlur={onBlur}
        value={raw ?? (typeof value === 'string' ? value : JSON.stringify(value ?? {}, null, 2))}
        onChange={event => {
          const text = event.target.value
          setRaw(text)
          try {
            const parsed: unknown = JSON.parse(text)
            onChange(isBookingSchedule(parsed) ? parsed : text)
          } catch { onChange(text) }
        }} />}
    </Field> : <>
      {error && <Alert tone="danger">{t('common.serverText', { text: error })}</Alert>}
      {Object.keys(schedule).some(key => !bookingWeekdays.some(day => day === key)) && <p>{t('connectC.invalidWeekdayHelp')}</p>}
      {bookingWeekdays.map(day => {
        const windows = schedule[day] ?? []
        const label = t('connectC.weekday.' + day)
        const weekdayTitle = t('connectC.weekdayTitle', { day: label, count: windows.length })
        return <Disclosure key={day} label={weekdayTitle}>
          <Stack>
            {windows.map((window, index) => <Grid key={index}>
              {(['start', 'end'] as const).map(edge => <Field key={edge} id={id + '-' + day + '-' + index + '-' + edge}
                label={t('connectC.window.' + edge, { index: index + 1 })} hint={t('connectC.help.wallTime')}>
                {attrs => <Input {...attrs} value={window[edge]} placeholder={t('connectC.timePlaceholder')}
                  pattern={timePattern} readOnly={readOnly} aria-invalid={error ? true : undefined}
                  onBlur={onBlur} onChange={event => editDay(day, windows.map((item, position) =>
                    position === index ? { ...item, [edge]: event.target.value } : item))} />}
              </Field>)}
              {!readOnly && <Row><ConfirmDestructive
                trigger={<Button variant="danger" aria-label={t('connectC.removeWindow', { day: label, index: index + 1 })}>{t('schema.remove')}</Button>}
                title={t('connectC.removeWindow', { day: label, index: index + 1 })} description={t('schema.removeHelp')} action={t('schema.remove')}
                onConfirm={() => { editDay(day, windows.filter((_, position) => position !== index)); onBlur() }} /></Row>}
            </Grid>)}
            {!readOnly && <Row><Button aria-label={t('connectC.addDayWindow', { day: label })} onClick={() =>
              editDay(day, [...windows, { start: '09:00', end: '17:00' }])}>{t('connectC.addWindow')}</Button></Row>}
          </Stack>
        </Disclosure>
      })}
    </>}
  </Stack></fieldset>
}

export function PackSummary({ title, items }: { title: string; items: [string, ReactNode][] }) {
  const t = useT()
  return <Stack><h3>{title}</h3><Table label={title}
    columns={['setting', 'value'].map(id => ({ id, label: t('connectC.column.' + id) }))}
    rows={items.map(([label, value]) => ({ id: label, cells: [label, value] }))} /></Stack>
}
