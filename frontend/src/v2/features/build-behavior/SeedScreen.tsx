import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import type { SeedEntityBody, SeedFieldBody, SeedGeneratorBody, SeedProfileBody, SequenceBody } from '../../../api/types'
import { useT } from '../../i18n'
import { SettingsSection } from '../../patterns'
import { Button, Card, EmptyState, Row, Stack, useToast } from '../../ui'
import { behaviorIdentifier, booleanValue, hookDateTime, lineValues, seedDate, seedEmailPrefix, seedPrefix, validators } from '../../validators'
import { catalogOptions, seedSection, sequenceSection, specOptions } from './api/behavior'
import type { Catalog, CatalogEntity } from './api/behavior'
import {
  BehaviorField, BehaviorPage, BehaviorSelect, Choices, FormGrid, RemoveAction, SectionForm, queryStates, Summary, WholeNumber, canEdit, removeAt, replaceAt,
} from './BehaviorForm'
import type { BehaviorProps } from './BehaviorForm'
import { freshPlan, freshProfile, makeGenerator, preferredGenerator, reachable, targetsFor, tenantScoped, typedSeedValue, wholeTypes } from './seed'
import type { SeedTarget } from './seed'

const route = '/projects/$projectId/$section'
const maxRows = 10000

function Commands({ name }: { name: string }) {
  const t = useT()
  const toast = useToast()
  const prefix = 'python -m app.seed'
  const profile = /^[a-z][a-z0-9_]{0,23}$/.test(name) ? name : 'NAME'
  const base = prefix + ' --profile ' + profile
  const commands = [
    ['create', base], ['reset', base + ' --reset'], ['check', prefix + ' --check'],
    ['list', prefix + ' --list'], ['resetOnly', base + ' --reset-only'],
  ]
  return <SettingsSection title={t('behavior.seed.run')} description={t('behavior.seed.runHelp')}>
    {commands.map(([key, command]) => <Stack key={key} gap={1}>
      <strong>{t('behavior.seed.command.' + key)}</strong>
      <Row className="v2-spread">
        <code>{command}</code>
        <Button onClick={() => void navigator.clipboard.writeText(command).then(
          () => toast({ title: t('behavior.copied'), tone: 'success' }),
          () => toast({ title: t('behavior.copyError'), tone: 'danger' }),
        )}>{t('behavior.copy')}</Button>
      </Row>
    </Stack>)}
    <p className="v2-muted">{t('behavior.seed.guard')}</p>
  </SettingsSection>
}

function GeneratorEditor({ generator, target, entity, edit, path }: {
  generator: SeedGeneratorBody; target?: SeedTarget; entity: CatalogEntity; edit: (value: SeedGeneratorBody) => void; path: string
}) {
  const t = useT()
  const label = (key: string) => t('behavior.seed.param.' + key)
  const { type } = generator
  const column = target?.column
  const columnType = column?.type ?? ''
  const whole = wholeTypes.includes(columnType)
  const bounds = whole ? columnType === 'integer' ? [-(2 ** 31), 2 ** 31 - 1] : [-Number.MAX_SAFE_INTEGER, Number.MAX_SAFE_INTEGER]
    : [-(10 ** 12) + 1, 10 ** 12 - 1]
  const min = Math.max(column?.min_value ?? -Infinity, bounds[0])
  const max = Math.min(column?.max_value ?? Infinity, bounds[1])
  const field = (key: keyof SeedGeneratorBody) => path + '.' + key
  const number = (key: 'width' | 'start' | 'places' | 'min_words' | 'max_words', fallback: number, lower: number, upper: number) =>
    <WholeNumber label={label(key)} path={field(key)} value={generator[key] ?? fallback} min={lower} max={upper}
      change={value => edit({ ...generator, [key]: value })} />
  const textChecks = columnType === 'boolean' ? [validators.required, booleanValue]
    : columnType === 'date' ? [validators.required, seedDate] : columnType === 'datetime' ? [validators.required, hookDateTime]
      : ['integer', 'bigint', 'float', 'decimal'].includes(columnType) ? [validators.required,
        validators.number({ min, max, integer: whole, digits: 18 })] : [validators.length(Math.min(column?.max_length ?? 200, 200))]
  if (type === 'constant') {
    const values = columnType === 'enum' ? column?.enum_values ?? [] : columnType === 'boolean' ? ['true', 'false'] : null
    const editValue = (value: string) => edit({ ...generator, value: typedSeedValue(value, columnType) })
    return values ? <BehaviorSelect label={label('value')} path={field('value')} value={String(generator.value ?? '')} change={editValue} options={values} />
      : <BehaviorField label={label('value')} path={field('value')} value={generator.value} change={editValue} checks={textChecks} />
  }
  if (type === 'one_of') {
    const values = (generator.values ?? []).map(String)
    const select = columnType === 'enum' ? column?.enum_values ?? [] : columnType === 'boolean' ? ['true', 'false'] : null
    return select ? <Choices label={label('values')} path={field('values')} values={values} options={select} required max={100}
      change={next => edit({ ...generator, values: next.map(value => typedSeedValue(value, columnType)) })} />
      : <OneOfValues label={label('values')} path={field('values')} value={values.join('\n')} checks={textChecks}
        change={next => edit({ ...generator, values: next.split('\n').map(line => line.trim()).filter(Boolean).map(value => typedSeedValue(value, columnType)) })} />
  }
  if (type === 'state') return <FormGrid>
    {reachable(entity).map(state => <WholeNumber key={state} label={t('behavior.seed.weight', { state })} path={field('weights') + '.' + state}
      value={generator.weights?.[state] ?? 0} min={0} max={1000}
      change={value => edit({ ...generator, weights: { ...generator.weights, [state]: value ?? 0 } })} />)}
  </FormGrid>
  if (type === 'reference') return <FormGrid>
    <BehaviorSelect label={label('entity')} path={field('entity')} value={generator.entity}
      options={target?.reference?.target ? [target.reference.target] : []} change={value => edit({ ...generator, entity: value })} />
    <BehaviorSelect label={label('pick')} path={field('pick')} value={generator.pick ?? 'cycle'} options={target?.reference?.unique ? ['cycle'] : ['cycle', 'random']}
      change={pick => edit({ ...generator, pick })} />
  </FormGrid>
  if (type === 'words') return <FormGrid>
    {number('min_words', 1, 1, generator.max_words || 50)}
    {number('max_words', 3, generator.min_words || 1, 50)}
  </FormGrid>
  if (type === 'bool_ratio') return <Ratio label={label('ratio')} path={field('ratio')} value={generator.ratio}
    change={value => edit({ ...generator, ratio: value })} />
  if (type === 'sequence' || type === 'email') return <FormGrid>
    {!whole && <BehaviorField label={label('prefix')} path={field('prefix')} value={generator.prefix ?? (type === 'email' ? 'user' : '')}
      maxLength={type === 'email' ? 20 : 40} checks={type === 'email' ? [validators.required, seedEmailPrefix] : [seedPrefix]}
      change={prefix => edit({ ...generator, prefix })} />}
    {type === 'sequence' && number('start', 0, 0, 1000000000)}
    {type === 'sequence' && !whole && number('width', 0, 0, 12)}
  </FormGrid>
  if (['date_range', 'int_range', 'decimal_range'].includes(type)) return <FormGrid>
    {(['min', 'max'] as const).map(key => type === 'int_range'
      ? <WholeNumber key={key} label={label(key)} path={field(key)} value={generator[key] == null ? null : Number(generator[key])}
        min={key === 'max' ? Math.max(min, Number(generator.min ?? min)) : min}
        max={key === 'min' ? Math.min(max, Number(generator.max ?? max)) : max} change={value => edit({ ...generator, [key]: value })} />
      : <BehaviorField key={key} label={label(key)} path={field(key)} type={type === 'date_range' ? 'date' : undefined}
        value={generator[key]} checks={[validators.required, type === 'date_range' ? seedDate : validators.number({ min, max, digits: 18 })]}
        change={value => edit({ ...generator, [key]: value })} />)}
    {type === 'decimal_range' && number('places', 0, 0, 6)}
  </FormGrid>
  return null
}

function OneOfValues({ value, change, label, path, checks }: {
  value: string; change: (text: string) => void; label: string; path: string; checks: Parameters<typeof lineValues>[0]
}) {
  const t = useT()
  const [raw, setRaw] = useState<string>()
  return <BehaviorField area label={label} path={path} hint={t('behavior.seed.onePerLine')}
    value={raw ?? value} checks={[lineValues(checks, 100)]} change={text => { setRaw(text); change(text) }} />
}

function Ratio({ value, change, label, path }: {
  value?: number | null; change: (value: number) => void; label: string; path: string
}) {
  const [raw, setRaw] = useState<string>()
  return <BehaviorField label={label} path={path} value={raw ?? value}
    checks={[validators.required, validators.number({ min: 0, max: 1 })]}
    change={text => { setRaw(text); change(text.trim() ? Number(text) : NaN) }} />
}

function EntityPlan({ plan, index, prefix, entities, profile, sequences, edit, remove, disabled, scoped }: {
  plan: SeedEntityBody; index: number; prefix: string; entities: Catalog; profile: SeedProfileBody;
  sequences: SequenceBody[]; edit: (value: SeedEntityBody) => void; remove: () => void; disabled: boolean; scoped: Set<string>
}) {
  const t = useT()
  const label = (key: string) => t('behavior.seed.' + key)
  const path = (key: string) => prefix + '.entities.' + index + '.' + key
  const entity = entities.entities.find(item => item.name === plan.entity)
  const fields = plan.fields ?? []
  const targets = entity ? targetsFor(entity, sequences) : []
  const unused = targets.filter(target => target.options.length && !fields.some(field => field.field === target.name))
  const required = unused.filter(target => target.required)
  const choices = entities.entities.filter(item => item.name === plan.entity || !profile.entities?.some(other => other.entity === item.name))
  const add = (items: SeedTarget[]) => {
    if (!entity) return
    edit({ ...plan, fields: [...fields, ...items.slice(0, Math.max(0, 100 - fields.length)).map(target => ({
      field: target.name, generator: makeGenerator(preferredGenerator(target), target, entity, profile.as_of),
    }))] })
  }
  const changeField = (position: number, value: SeedFieldBody) => edit({ ...plan, fields: replaceAt(fields, position, value) })
  const perTenant = scoped.has(plan.entity)
  return <SettingsSection title={plan.entity}>
    <FormGrid>
      <BehaviorSelect label={label('entity')} path={path('entity')} value={plan.entity} options={choices.map(item => item.name)}
        change={next => edit({ ...freshPlan(next), count: plan.count })} />
      <WholeNumber label={label('rows')} path={path('count')} value={plan.count} min={0}
        max={Math.floor(maxRows / (perTenant ? Math.max(1, profile.tenants || 0) : 1))}
        hint={label(perTenant ? 'rowsPerTenant' : 'rowsTotal')} change={count => edit({ ...plan, count: count ?? 0 })} />
    </FormGrid>
    <Row><RemoveAction label={label('removePlan')} onConfirm={remove} /></Row>
    {fields.map((field, position) => {
      const target = targets.find(item => item.name === field.field)
      const full = path('fields.' + position + '.generator')
      return <Card key={position} data-testid="seed-field-plan"><Stack>
        <h3>{field.field}</h3>
        <BehaviorSelect label={label('generator')} path={full + '.type'} value={field.generator.type} options={target?.options ?? []}
          hint={target?.options.includes(field.generator.type) ? label('generatorHint.' + field.generator.type) : label('generatorUnavailable')}
          change={type => {
            if (target && entity) changeField(position, { ...field, generator: makeGenerator(type, target, entity, profile.as_of) })
          }} />
        {entity && <GeneratorEditor key={field.generator.type} generator={field.generator} target={target} entity={entity}
          path={full} edit={generator => changeField(position, { ...field, generator })} />}
        <Row><RemoveAction label={label('removeField')} onConfirm={() => edit({ ...plan, fields: removeAt(fields, position) })} /></Row>
      </Stack></Card>
    })}
    {!!required.length && <Row><Button disabled={disabled || fields.length + required.length > 100} onClick={() => add(required)}>
      {t('behavior.seed.addRequired', { count: required.length, names: required.map(target => target.name).join(', ') })}
    </Button></Row>}
    {!!unused.length && <BehaviorSelect label={label('addField')} placeholder={label('chooseField')} value=""
      disabled={fields.length >= 100} options={unused.map(item => item.name)} change={value => add(unused.filter(target => target.name === value))} />}
  </SettingsSection>
}

function Profile({ profile, index, edit, remove, disabled, writable, catalog, sequences, scoped, fresh, edited }: {
  profile: SeedProfileBody; index: number; edit: (value: SeedProfileBody) => void; remove: () => void; disabled: boolean;
  writable: boolean; catalog: Catalog; sequences: SequenceBody[]; scoped: Set<string>; fresh: boolean; edited: boolean
}) {
  const t = useT()
  const label = (key: string) => t('behavior.seed.' + key)
  const [open, setOpen] = useState(fresh)
  const path = (key: string) => index + '.' + key
  const plans = profile.entities ?? []
  const choices = catalog.entities.filter(entity => !plans.some(plan => plan.entity === entity.name))
  const total = plans.reduce((sum, plan) => sum + (plan.count || 0) * (scoped.has(plan.entity) ? Math.max(1, profile.tenants || 0) : 1), 0)
  return <Card data-testid="seed-row" className="behavior-card"><Stack gap={4}>
    <Row className="v2-spread">
      <h2>{profile.name || label('new')}</h2>
      {writable && <Row>
        <Button data-behavior-edit-toggle disabled={disabled} aria-expanded={open} onClick={() => setOpen(!open)}>{t(open ? 'behavior.doneEditing' : 'behavior.edit')}</Button>
        <RemoveAction label={t('behavior.seed.removeProfile', { name: profile.name || label('new') })} onConfirm={remove} />
      </Row>}
    </Row>
    {writable && (open || edited) && <div hidden={!open} data-behavior-editor><Stack>
      <FormGrid>
        <BehaviorField label={label('name')} value={profile.name} path={path('name')} maxLength={24} checks={[validators.required, behaviorIdentifier(24)]}
          change={name => edit({ ...profile, name })} />
        <WholeNumber label={label('number')} value={profile.seed} path={path('seed')} min={0} max={2147483647}
          hint={label('numberHelp')} change={seed => edit({ ...profile, seed: seed ?? 42 })} />
        <BehaviorField label={label('asOf')} value={profile.as_of} path={path('as_of')} type="date" checks={[validators.required, seedDate]}
          change={as_of => edit({ ...profile, as_of })} />
        <WholeNumber label={label('tenants')} value={profile.tenants ?? 0} path={path('tenants')} min={0} max={20}
          hint={label('tenantsHelp')} change={tenants => edit({ ...profile, tenants: tenants ?? 0 })} />
      </FormGrid>
      <p className="v2-muted">{t('behavior.seed.total', { count: total, max: 50000 })}</p>
      <h3>{label('plans')}</h3>
      {plans.map((plan, position) => <EntityPlan key={position + ':' + plan.entity} plan={plan} index={position} prefix={String(index)}
        profile={profile} entities={catalog} sequences={sequences} disabled={disabled} scoped={scoped}
        edit={next => edit({ ...profile, entities: replaceAt(plans, position, next) })}
        remove={() => edit({ ...profile, entities: removeAt(plans, position) })} />)}
      {!!choices.length && <BehaviorSelect label={label('addEntity')} value="" placeholder={label('chooseEntity')}
        options={choices.map(choice => choice.name)} change={name => edit({ ...profile, entities: [...plans, freshPlan(name)] })} />}
    </Stack></div>}
    {(!open || !writable) && <Summary testId="seed-summary" entries={[
      { label: label('number'), value: new Intl.NumberFormat().format(profile.seed) },
      { label: label('asOf'), value: profile.as_of },
      { label: label('tenants'), value: new Intl.NumberFormat().format(profile.tenants ?? 0) },
      { label: label('plans'), value: plans.length ? <Stack gap={1}>{plans.map(plan =>
        <span key={plan.entity}>{t('behavior.seed.planSummary', { name: plan.entity, rows: plan.count, fields: plan.fields?.length ?? 0 })}</span>)}</Stack> : t('behavior.none') },
    ]} />}
    <Commands name={profile.name} />
  </Stack></Card>
}

export default function SeedScreen(props: BehaviorProps) {
  const t = useT()
  const { projectId } = props
  const catalog = useQuery(catalogOptions(projectId))
  const sequences = useQuery(sequenceSection.query(projectId))
  const spec = useQuery(specOptions(projectId))
  const writable = canEdit(props.role)
  return <BehaviorPage title={t('nav.seed')} description={t('behavior.seed.intro')} access={props}>
    <SectionForm projectId={projectId} config={seedSection} supporting={queryStates(catalog, sequences, spec)} writable={writable}
      render={({ value, saved, edit, disabled }) => {
        if (!catalog.data) return null
        const data = catalog.data
        const scoped = new Set(data.entities.filter(entity => tenantScoped(spec.data, entity)).map(entity => entity.name))
        const add = data.entities.length ? <Button variant="primary" disabled={disabled || value.length >= 5}
          onClick={() => edit([...value, freshProfile(value)])}>{t('behavior.seed.add')}</Button>
          : <Button asChild><Link to={route} params={{ projectId, section: 'model' }}>{t('nav.model')}</Link></Button>
        return <Stack gap={4}>
          {!value.length && <EmptyState title={t('behavior.seed.empty')} description={t(data.entities.length ? 'behavior.seed.emptyHelp' : 'behavior.seed.noEntity')} action={add} />}
          {value.map((profile, index) => <Profile key={index} profile={profile} index={index} disabled={disabled} writable={writable} catalog={data}
            sequences={sequences.data?.value ?? []} scoped={scoped} fresh={index >= saved.length} edited={!saved.includes(profile)}
            edit={next => edit(replaceAt(value, index, next))} remove={() => edit(removeAt(value, index))} />)}
          {!!value.length && <Row>{add}</Row>}
          <p className="v2-muted">{t('behavior.seed.profileLimit')}</p>
        </Stack>
      }} />
  </BehaviorPage>
}
