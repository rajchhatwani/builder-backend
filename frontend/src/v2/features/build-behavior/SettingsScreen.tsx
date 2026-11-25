import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import type { ListBody, SequenceBody, SettingBody } from '../../../api/types'
import { useT } from '../../i18n'
import { SettingsSection } from '../../patterns'
import { Button, Card, EmptyState, Row, Stack, Tabs } from '../../ui'
import { behaviorIdentifier, booleanValue, publicBehaviorName, sequencePrefix, settingColor, settingDecimal, validators } from '../../validators'
import { catalogOptions, listSection, rolesOptions, sequenceSection, settingsSection } from './api/behavior'
import type { Catalog } from './api/behavior'
import {
  BehaviorCheck, BehaviorField, BehaviorPage, BehaviorSelect, Choices, FormGrid, RemoveAction, SectionForm, queryStates, WholeNumber, canEdit, removeAt, replaceAt,
} from './BehaviorForm'
import type { BehaviorProps } from './BehaviorForm'

const types = ['string', 'int', 'bool', 'decimal']
const tabs = ['settings', 'sequences', 'lists'] as const
type Tab = typeof tabs[number]
type Role = { value: string; label: string }
const identifier = [validators.required, behaviorIdentifier(60)]
const maxInt = Number.MAX_SAFE_INTEGER
const limits = { settings: 200, sequences: 50, lists: 100 }
const route = '/projects/$projectId/$section'

type RowProps<T> = { row: T; index: number; edit: (row: T) => void; roles: Role[] }

function Setting({ row, index, edit, roles }: RowProps<SettingBody>) {
  const t = useT()
  const label = (key: string) => t('behavior.settings.' + key)
  const path = (key: string) => index + '.' + key
  const kind = row.type ?? 'string'
  const isNumeric = kind === 'int' || kind === 'decimal'
  const number = kind === 'decimal' ? settingDecimal : validators.number({ integer: true, min: -maxInt, max: maxInt, digits: 16 })
  const typed = (text: string) => kind === 'int' && !number(text) && text.trim() ? Number(text) :
    kind === 'bool' && /^(true|false)$/i.test(text) ? text.toLowerCase() === 'true' : text
  return <Stack>
    <FormGrid>
      <BehaviorField label={label('name')} path={path('key')} value={row.key} maxLength={60}
        checks={[...identifier, publicBehaviorName]} hint={label('secretHelp')} change={key => edit({ ...row, key })} />
      <BehaviorSelect label={label('type')} path={path('type')} value={kind} options={types}
        change={type => edit({ ...row, type, default: type === 'bool' ? false : type === 'int' ? 0 : type === 'decimal' ? '0' : '',
          minimum: null, maximum: null, max_length: null })} />
      <BehaviorField label={label('default')} path={path('default')} value={row.default}
        maxLength={kind === 'string' ? Math.min(row.max_length || 200, 2000) : 120}
        checks={isNumeric ? [validators.required, number] : kind === 'bool' ? [validators.required, booleanValue] : []}
        change={text => edit({ ...row, default: typed(text) })} />
      {isNumeric && (['minimum', 'maximum'] as const).map(bound => <BehaviorField key={bound} label={label(bound)} path={path(bound)}
        value={row[bound]} checks={[number]} change={text => edit({ ...row, [bound]: text.trim() ? typed(text) : null })} />)}
      {kind === 'string' && <WholeNumber label={label('length')} path={path('max_length')} value={row.max_length}
        optional min={1} max={2000} change={max_length => edit({ ...row, max_length })} />}
      <BehaviorField label={label('label')} path={path('label')} value={row.label} maxLength={120} change={value => edit({ ...row, label: value || null })} />
      <BehaviorField area label={label('description')} path={path('description')} value={row.description} maxLength={1000}
        change={description => edit({ ...row, description: description || null })} />
    </FormGrid>
    <Choices label={label('readRoles')} path={path('read_roles')} hint={label('readHelp')} options={roles}
      values={row.read_roles ?? []} change={read_roles => edit({ ...row, read_roles })} />
    <Choices label={label('editRoles')} path={path('edit_roles')} hint={label('editHelp')} options={roles}
      values={row.edit_roles ?? []} change={edit_roles => edit({ ...row, edit_roles })} />
  </Stack>
}

function Sequence({ row, index, edit, roles, catalog }: RowProps<SequenceBody> & { catalog?: Catalog }) {
  const t = useT()
  const label = (key: string) => t('behavior.settings.' + key)
  const path = (key: string) => index + '.' + key
  const entity = catalog?.entities.find(item => item.name === row.entity)
  const fields = entity?.columns.filter(field => (field.type === 'string' ||
    (field.type === 'bigint' && !row.prefix && !row.reset_yearly && !row.padding)) &&
    field.name !== entity.machine?.field && field.required && field.unique && field.default == null) ?? []
  const number = (row.prefix ?? '') + (row.reset_yearly ? new Date().getFullYear() + '-' : '') +
    String(row.start ?? 1).padStart(Math.min(12, row.padding || 0), '0')
  return <Stack>
    <FormGrid>
      <BehaviorField label={label('name')} value={row.name} path={path('name')} maxLength={60} checks={[...identifier, publicBehaviorName]} change={name => edit({ ...row, name })} />
      <BehaviorField label={label('prefix')} value={row.prefix} path={path('prefix')} maxLength={20} checks={[sequencePrefix]} change={prefix => edit({ ...row, prefix })} />
      <WholeNumber label={label('padding')} value={row.padding ?? 0} path={path('padding')} min={0} max={12} change={value => edit({ ...row, padding: value ?? 0 })} />
      <WholeNumber label={label('start')} value={row.start ?? 1} path={path('start')} min={0} max={maxInt} change={value => edit({ ...row, start: value ?? 1 })} />
      <BehaviorSelect label={label('boundEntity')} path={path('entity')} value={row.entity} optional options={catalog?.entities.map(item => item.name) ?? []}
        change={next => edit({ ...row, entity: next || null, field: null })} />
      <BehaviorSelect label={label('boundField')} path={path('field')} value={row.field} optional options={fields.map(field => field.name)}
        hint={label('boundHelp')} disabled={!row.entity} change={field => edit({ ...row, field: field || null })} />
    </FormGrid>
    <Choices label={label('viewCounters')} path={path('view_roles')} options={roles} values={row.view_roles ?? []}
      change={view_roles => edit({ ...row, view_roles })} />
    <Row>
      <BehaviorCheck label={label('tenant')} value={row.per_tenant} path={path('per_tenant')} change={per_tenant => edit({ ...row, per_tenant })} />
      <BehaviorCheck label={label('yearly')} value={row.reset_yearly} path={path('reset_yearly')} change={reset_yearly => edit({ ...row, reset_yearly })} />
    </Row>
    <p>{label('preview')} <code data-testid="seq-preview">{number}</code></p>
  </Stack>
}

function List({ row, index, edit, roles, disabled }: RowProps<ListBody> & { disabled: boolean }) {
  const t = useT()
  const label = (key: string) => t('behavior.settings.' + key)
  const path = (key: string) => index + '.' + key
  const items = row.items ?? []
  return <Stack>
    <FormGrid>
      <BehaviorField label={label('name')} value={row.name} path={path('name')} maxLength={60} checks={identifier} change={name => edit({ ...row, name })} />
      <BehaviorField label={label('label')} value={row.label} path={path('label')} maxLength={120} change={value => edit({ ...row, label: value || null })} />
      <WholeNumber label={label('maxItems')} value={row.max_items ?? 100} path={path('max_items')} min={Math.max(1, items.length)} max={500}
        change={max => edit({ ...row, max_items: max ?? 100 })} />
    </FormGrid>
    <Choices label={label('listRoles')} path={path('edit_roles')} options={roles} values={row.edit_roles ?? []} change={edit_roles => edit({ ...row, edit_roles })} />
    {items.map((item, position) => {
      const change = (value: typeof item) => edit({ ...row, items: replaceAt(items, position, value) })
      const field = (key: string) => path('items.' + position + '.' + key)
      return <Card key={position}><Stack>
        <h3>{t('behavior.settings.item', { count: position + 1 })}</h3>
        <FormGrid>
          <BehaviorField label={label('value')} path={field('value')} value={item.value} maxLength={40} checks={[validators.required, behaviorIdentifier(40)]} change={value => change({ ...item, value })} />
          <BehaviorField label={label('label')} path={field('label')} value={item.label} maxLength={80} checks={[validators.required]} change={value => change({ ...item, label: value })} />
          <BehaviorField label={label('color')} path={field('color')} value={item.color} maxLength={7} checks={[settingColor]}
            hint={t('validation.settingColor')} change={color => change({ ...item, color: color || null })} />
          <BehaviorCheck label={label('locked')} path={field('locked')} value={item.locked} change={locked => change({ ...item, locked })} />
        </FormGrid>
        <Row><RemoveAction label={label('removeItem')} onConfirm={() => edit({ ...row, items: removeAt(items, position) })} /></Row>
      </Stack></Card>
    })}
    <Row><Button disabled={disabled || items.length >= Math.min(row.max_items || 100, 500)}
      onClick={() => edit({ ...row, items: [...items, { value: '', label: '', locked: false }] })}>{label('addItem')}</Button></Row>
  </Stack>
}

function Rows<T>({ kind, value, edit, disabled, blank, title, content }: {
  kind: Tab; value: T[]; edit: (value: T[]) => void; disabled: boolean;
  blank: T; title: (row: T) => string; content: (row: T, index: number, update: (row: T) => void) => ReactNode
}) {
  const t = useT()
  const add = <Button variant="primary" disabled={disabled || value.length >= limits[kind]} onClick={() => edit([...value, blank])}>
    {t('behavior.settings.add.' + kind)}
  </Button>
  if (!value.length) return <EmptyState title={t('behavior.settings.empty.' + kind)} description={t('behavior.settings.intro.' + kind)} action={add} />
  return <Stack>
    <p className="v2-muted">{t('behavior.settings.count.' + kind, { count: value.length, max: limits[kind] })}</p>
    {value.map((row, index) => <SettingsSection key={index} title={title(row) || t('behavior.settings.new.' + kind)}>
      {content(row, index, next => edit(replaceAt(value, index, next)))}
      <Row><RemoveAction label={t('behavior.settings.remove.' + kind)} onConfirm={() => edit(removeAt(value, index))} /></Row>
    </SettingsSection>)}
    <Row>{add}</Row>
  </Stack>
}

export default function SettingsScreen(props: BehaviorProps) {
  const t = useT()
  const { tab: searchTab } = useSearch({ from: route })
  const navigate = useNavigate({ from: route })
  const tab = tabs.find(value => value === searchTab) ?? 'settings'
  const { projectId } = props
  const rolesQuery = useQuery(rolesOptions(projectId))
  const catalog = useQuery(catalogOptions(projectId))
  const roles = rolesQuery.data?.roles.map(role => ({ value: role.name, label: role.label || role.name })) ?? []
  const writable = canEdit(props.role)
  const contents = {
    settings: <SectionForm projectId={projectId} config={settingsSection} supporting={queryStates(rolesQuery)} writable={writable} render={state =>
      <Rows {...state} kind="settings" blank={{ key: '', type: 'string', default: '' }} title={row => row.label || row.key}
        content={(row, index, edit) => <Setting {...{ row, index, edit, roles }} />} />} />,
    sequences: <SectionForm projectId={projectId} config={sequenceSection} supporting={queryStates(rolesQuery, catalog)} writable={writable} render={state =>
      <Rows {...state} kind="sequences" blank={{ name: '', start: 1 }} title={row => row.name}
        content={(row, index, edit) => <Sequence {...{ row, index, edit, roles }} catalog={catalog.data} />} />} />,
    lists: <SectionForm projectId={projectId} config={listSection} supporting={queryStates(rolesQuery)} writable={writable} render={state =>
      <Rows {...state} kind="lists" blank={{ name: '', max_items: 100 }} title={row => row.label || row.name}
        content={(row, index, edit) => <List {...{ row, index, edit, roles }} disabled={state.disabled} />} />} />,
  }
  return <BehaviorPage title={t('nav.settings')} description={t('behavior.settings.intro.' + tab)} access={props}>
    <Tabs label={t('behavior.settings.tabs')} keepMounted value={tab}
      onChange={next => void navigate({ params: { projectId, section: 'settings' }, search: previous => ({ ...previous, tab: next }) })}
      items={tabs.map(id => ({ id, label: t('behavior.section.' + id), content: contents[id] }))} />
  </BehaviorPage>
}
