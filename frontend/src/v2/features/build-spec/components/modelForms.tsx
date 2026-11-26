import { useState } from 'react'
import type { Entity, EntityOptions, Field as FieldData, FieldInput, FieldType, OnDelete, Relation, RelationKind } from '../../../../api/types'
import { useT } from '../../../i18n'
import { Form } from '../../../patterns'
import type { FormField } from '../../../patterns'
import { Alert, Checkbox, Dialog, Input, Select, Textarea } from '../../../ui'
import {
  buildLimits, csvNames, defaultLimits, enumChoices, fieldDefault, pascalName, snakeName, validateFieldDefault, validators,
} from '../../../validators'
import type { ValidationIssue, Validator } from '../../../validators'
import { buildError, serverIssues } from '../api/build'
import type { ModelWrite } from '../api/build'
import { BuildFailure, ChoiceGroup, Pick, choices } from './shared'

export const operationNames = ['list', 'get', 'head', 'create', 'replace', 'update', 'delete']
const fieldTypes: FieldType[] = ['string', 'text', 'integer', 'bigint', 'float', 'decimal', 'boolean', 'date', 'datetime', 'uuid', 'json', 'enum', 'file']
const numeric = ['integer', 'bigint', 'float', 'decimal']
const kinds: RelationKind[] = ['one_to_many', 'many_to_many', 'one_to_one']
const deleteOptions: OnDelete[] = ['restrict', 'cascade', 'set_null']
const integer = (min: number, max: number, digits?: number) => validators.number({ min, max, integer: true, digits })
const value = (data: FormData, name: string) => String(data.get(name) ?? '').trim()
const number = (data: FormData, name: string) => value(data, name) === '' ? null : Number(value(data, name))
const duplicate = (list: string[], original?: string): Validator => name =>
  name.trim() !== original && list.includes(name.trim()) ? { key: 'buildSpec.model.duplicate' } : undefined
const entityDefaults: EntityOptions = {
  operations: operationNames, filterable: [], sortable: [], searchable: [], default_page_size: 20, max_page_size: 100, soft_delete: false,
}
const stringField = (name: string, label: string, initial: string | undefined, validate: Validator[], attributes: {
  type?: 'number' | 'text'; maxLength?: number; min?: number; max?: number; step?: string;
} = {}): FormField => ({ name, label, validate, control: attrs => <Input {...attrs} {...attributes} defaultValue={initial} /> })

function fieldErrors(error: unknown, fields: FormField[]): Record<string, ValidationIssue> | undefined {
  const details = serverIssues(error)
  if (buildError(error)?.code === 'conflict' && fields.some(field => field.name === 'name')) {
    return { name: { key: 'buildSpec.message', values: { message: buildError(error)!.message } } }
  }
  const known = fields.flatMap(field => {
    const detail = details.find(issue => issue.path.split('.').at(-1) === field.name)
    return detail ? [[field.name, { key: 'buildSpec.message', values: { message: detail.message } }]] : []
  })
  return known.length ? Object.fromEntries(known) : undefined
}

type EntityInput = Extract<ModelWrite, { kind: 'addEntity' }>['data']
export function EntityForm({ entity, entities, fields, derived, close, optionsOnly, pending, disabled, error, onSave }: {
  entity?: Entity; entities: Entity[]; fields: FieldData[]; derived: string[]; close?: () => void; optionsOnly?: boolean;
  pending: boolean; disabled: boolean; error: unknown; onSave: (data: EntityInput) => void
}) {
  const t = useT()
  const initial = entity?.options ?? entityDefaults
  const [patch, setPatch] = useState<Partial<EntityOptions>>({})
  const options = { ...initial, ...patch }
  const rename = entity && !optionsOnly
  const nameFields: FormField[] = optionsOnly ? [] : [stringField('name', t('buildSpec.name'), entity?.name,
    [validators.required, validators.length(buildLimits.identifier), pascalName, duplicate(entities.map(item => item.name), entity?.name)],
    { maxLength: buildLimits.identifier })]
  const settings: FormField[] = rename ? [] : [
    ...(['table_name', 'plural_path'] as const).map(key => stringField(key, t('buildSpec.model.' + key), entity?.[key],
      [...entity ? [validators.required] : [], validators.length(buildLimits.identifier), snakeName, duplicate(entities.map(item => item[key]), entity?.[key])],
      { maxLength: buildLimits.identifier })),
    stringField('default_page_size', t('buildSpec.model.defaultPage'), String(initial.default_page_size),
      [validators.required, integer(1, 500)], { type: 'number', min: 1, max: 500 }),
    {
      ...stringField('max_page_size', t('buildSpec.model.maxPage'), String(initial.max_page_size),
        [validators.required, integer(1, 1000)], { type: 'number', min: 1, max: 1000 }),
      validateWith: (input, data) => Number(input) < Number(value(data, 'default_page_size')) ? { key: 'buildSpec.model.pageOrder' } : undefined,
    },
  ]
  const formFields = [...nameFields, ...settings]
  const mapped = fieldErrors(error, formFields)
  const locked = pending || disabled
  const body = <Form fields={formFields} readOnly={disabled} pending={pending} serverErrors={mapped}
    submitLabel={t(rename ? 'buildSpec.model.rename' : entity ? 'buildSpec.model.saveOptions' : 'buildSpec.model.create')}
    onSubmit={data => {
      const name = optionsOnly ? entity!.name : value(data, 'name')
      if (rename) { onSave({ name }); return }
      const table_name = value(data, 'table_name') || undefined
      const plural_path = value(data, 'plural_path') || undefined
      const nextOptions = {
        ...options, default_page_size: Number(data.get('default_page_size')), max_page_size: Number(data.get('max_page_size')),
      }
      onSave({ name, table_name, plural_path, options: nextOptions })
    }}>
    {!rename && <>
      <ChoiceGroup label={t('buildSpec.model.operations')} options={operationNames.map(value => ({ value, label: t('buildSpec.operations.' + value) }))}
        selected={options.operations} onChange={operations => setPatch({ ...patch, operations })} disabled={locked} />
      {(['filterable', 'sortable', 'searchable'] as const).map(key => {
        const names = fields.filter(field => key === 'searchable' ? ['string', 'text'].includes(field.type)
          : !['file', 'json'].includes(field.type)).map(field => field.name)
        if (key !== 'searchable') names.push('id', 'created_at', 'updated_at', ...derived, ...(options.soft_delete ? ['deleted_at'] : []))
        return <ChoiceGroup key={key} label={t('buildSpec.model.' + key)} options={choices(names.filter(name => key !== 'filterable' || !['limit', 'offset', 'sort', 'q'].includes(name)))}
          selected={options[key]} onChange={values => setPatch({ ...patch, [key]: values })} disabled={locked} />
      })}
      <Checkbox label={t('buildSpec.model.softDelete')} checked={options.soft_delete} disabled={locked} onChange={event => {
        const soft_delete = event.target.checked
        setPatch(soft_delete ? { ...patch, soft_delete } : { ...patch, soft_delete,
          filterable: options.filterable.filter(name => name !== 'deleted_at'), sortable: options.sortable.filter(name => name !== 'deleted_at'),
        })
      }} />
    </>}
    {error != null && !mapped && <BuildFailure error={error} />}
  </Form>
  return close ? <Dialog open onOpenChange={open => { if (!open && !pending) close() }} title={t(rename ? 'buildSpec.model.rename' : 'buildSpec.model.add')}>{body}</Dialog> : body
}

export function FieldForm({ field, fields, reserved, pending, error, close, onSave }: {
  field?: FieldData; fields: FieldData[]; reserved: string[]; pending: boolean; error: unknown; close: () => void;
  onSave: (data: FieldInput & { position?: number }) => void
}) {
  const t = useT()
  const [type, setType] = useState<FieldType>(field?.type ?? 'string')
  const [required, setRequired] = useState(field?.required ?? false)
  const [unique, setUnique] = useState(field?.unique ?? false)
  const [indexed, setIndexed] = useState(field?.indexed ?? false)
  const [hasDefault, setHasDefault] = useState(field?.default !== undefined && field.default !== null)
  const numericType = numeric.includes(type)
  const uniqueAllowed = !['json', 'file'].includes(type)
  const numberChecks = [validators.number({ digits: 18, ...(type === 'decimal' ? { min: -1e12, max: 1e12 } :
    type === 'integer' ? { min: -2147483648, max: 2147483647 } :
    type === 'bigint' ? { min: -Number.MAX_SAFE_INTEGER, max: Number.MAX_SAFE_INTEGER } : {}) })]
  const formFields: FormField[] = [
    stringField('name', t('buildSpec.name'), field?.name, [validators.required, validators.length(buildLimits.identifier), snakeName,
      duplicate(fields.map(item => item.name), field?.name),
      input => reserved.includes(input.trim()) || /^(?:metadata|registry|copy|json|schema|validate|construct|fields|parse_obj|parse_raw|parse_file|from_orm|schema_json|update_forward_refs|model_.*)$/.test(input.trim())
        ? { key: 'buildSpec.model.reserved' } : undefined],
    { maxLength: buildLimits.identifier }),
    { name: 'type', label: t('buildSpec.model.type'), control: ({ name, disabled, ...attrs }) =>
      <Select name={name} disabled={disabled} triggerProps={attrs} options={fieldTypes.map(value => ({ value, label: t('buildSpec.fieldTypes.' + value) }))}
        value={type} onValueChange={v => setType(v as FieldType)} /> },
  ]
  if (type === 'string') formFields.push(stringField('max_length', t('buildSpec.model.maxLength'), field?.max_length?.toString(),
    [integer(1, 10000)], { type: 'number', min: 1, max: 10000 }))
  if (type === 'enum') formFields.push(stringField('enum_values', t('buildSpec.model.enumValues'), field?.enum_values?.join(', '), [enumChoices]))
  if (numericType) formFields.push(
    stringField('min_value', t('buildSpec.model.min'), field?.min_value?.toString(), numberChecks, { type: 'number', step: 'any' }),
    { ...stringField('max_value', t('buildSpec.model.max'), field?.max_value?.toString(), numberChecks, { type: 'number', step: 'any' }),
      validateWith: (input, data) => {
        const min = number(data, 'min_value')
        return min !== null && input && (Number(input) < min || (['integer', 'bigint'].includes(type) && Math.ceil(min) > Math.floor(Number(input))))
          ? { key: 'buildSpec.model.bounds' } : undefined
      } },
  )
  if (type !== 'file') formFields.push({
    name: 'defaultEnabled', label: t('buildSpec.model.defaultSetting'), control: ({ name, disabled, ...attrs }) =>
      <Select triggerProps={attrs} name={name} disabled={disabled} value={hasDefault ? 'value' : 'none'} onValueChange={choice => setHasDefault(choice === 'value')}
        options={[{ value: 'none', label: t('buildSpec.none') }, { value: 'value', label: t('buildSpec.model.useDefault') }]} />,
  })
  if (type !== 'file' && hasDefault) formFields.push({
    name: 'default', label: t('buildSpec.model.default'), validate: [...(['string', 'text'].includes(type) ? [] : [validators.required]), validateFieldDefault(type)],
    validateWith: (input, data) => {
      if (!input) return
      if (type === 'enum' && !csvNames(value(data, 'enum_values')).includes(input)) return { key: 'buildSpec.model.defaultEnum' }
      if (type === 'string' && [...input].length > (number(data, 'max_length') ?? 255)) return { key: 'buildSpec.model.defaultLength' }
      const min = number(data, 'min_value')
      const max = number(data, 'max_value')
      if (numericType && ((min !== null && Number(input) < min) || (max !== null && Number(input) > max))) return { key: 'buildSpec.model.defaultBounds' }
    },
    control: attrs => <Textarea {...attrs} key={type} maxLength={defaultLimits.longText}
      defaultValue={type !== field?.type || field.default == null ? '' : type === 'json' ? JSON.stringify(field.default) : String(field.default)} />,
  })
  formFields.push(stringField('position', t('buildSpec.model.position'), field?.position?.toString(),
    [integer(0, 2147483647, 10)], { type: 'number', min: 0, max: 2147483647 }))
  const mapped = fieldErrors(error, formFields)
  return <Dialog open title={t(field ? 'buildSpec.model.editField' : 'buildSpec.model.addField')} onOpenChange={open => { if (!open && !pending) close() }}>
    <Form fields={formFields} pending={pending} serverErrors={mapped} submitLabel={t('buildSpec.model.saveField')} onSubmit={data => {
      const position = number(data, 'position')
      onSave({
        name: value(data, 'name'), type, required, unique: uniqueAllowed && unique, indexed: type !== 'json' && indexed,
        default: type === 'file' || !hasDefault ? null : fieldDefault(type, String(data.get('default') ?? '')),
        min_value: numericType ? number(data, 'min_value') : null, max_value: numericType ? number(data, 'max_value') : null,
        max_length: type === 'string' ? number(data, 'max_length') : null, enum_values: type === 'enum' ? csvNames(value(data, 'enum_values')) : null,
        ...(position !== null ? { position } : {}),
      })
    }}>
      <Checkbox label={t('buildSpec.model.required')} checked={required} disabled={pending} onChange={event => setRequired(event.target.checked)} />
      <Checkbox label={t('buildSpec.model.unique')} checked={uniqueAllowed && unique} disabled={pending || !uniqueAllowed} onChange={event => setUnique(event.target.checked)} />
      <Checkbox label={t('buildSpec.model.indexed')} checked={type !== 'json' && indexed} disabled={pending || type === 'json'} onChange={event => setIndexed(event.target.checked)} />
      {type === 'file' && <Alert>{t('buildSpec.model.fileStorage')}</Alert>}
      {error != null && !mapped && <BuildFailure error={error} />}
    </Form>
  </Dialog>
}

type RelationInput = Extract<ModelWrite, { kind: 'relation' }>['data']
export function RelationForm({ entities, relation, entity, pending, error, close, onSave }: {
  entities: Entity[]; relation?: Relation; entity?: Entity; pending: boolean; error: unknown; close: () => void;
  onSave: (from: Entity, to: Entity, data: RelationInput) => void
}) {
  const t = useT()
  const [from, setFrom] = useState(relation?.from_entity_id ?? entity?.id ?? entities[0]?.id)
  const [to, setTo] = useState(relation?.to_entity_id ?? entities.find(item => item.id !== from)?.id)
  const [kind, setKind] = useState<RelationKind>(relation?.kind ?? 'one_to_many')
  const [required, setRequired] = useState(relation?.required ?? false)
  const [onDelete, setDelete] = useState<OnDelete>(relation?.on_delete ?? 'restrict')
  const options = entities.map(item => ({ value: item.id, label: item.name }))
  const formFields = (['from_name', 'to_name'] as const).map(key => stringField(key, t('buildSpec.model.' + key), relation?.[key],
    [validators.required, snakeName, validators.length(buildLimits.identifier)], { maxLength: buildLimits.identifier }))
  const mapped = fieldErrors(error, formFields)
  return <Dialog open title={t(relation ? 'buildSpec.model.editRelation' : 'buildSpec.model.addRelation')} onOpenChange={open => { if (!open && !pending) close() }}>
    <Form fields={formFields} pending={pending} serverErrors={mapped} submitLabel={t(relation ? 'common.save' : 'buildSpec.model.createRelation')} onSubmit={data => {
      const source = entities.find(item => item.id === from)
      const target = entities.find(item => item.id === to)
      if (source && target) onSave(source, target, {
        from_entity_id: source.id, to_entity_id: target.id, from_name: value(data, 'from_name'), to_name: value(data, 'to_name'),
        kind, required, on_delete: onDelete,
      })
    }}>
      <Pick label={t('buildSpec.model.fromEntity')} options={options} value={from} onChange={setFrom} disabled={pending || Boolean(relation)} />
      <Pick label={t('buildSpec.model.toEntity')} options={options} value={to} onChange={setTo} disabled={pending || Boolean(relation)} />
      <Pick label={t('buildSpec.model.kind')} options={kinds.map(value => ({ value, label: t('buildSpec.model.' + value) }))} value={kind}
        onChange={value => { setKind(value as RelationKind); if (value === 'many_to_many' && onDelete === 'set_null') setDelete('restrict') }}
        disabled={pending || Boolean(relation)} />
      <Pick label={t('buildSpec.model.onDelete')} options={deleteOptions.map(value => ({
        value, label: t('buildSpec.model.' + value), disabled: value === 'set_null' && (required || kind === 'many_to_many'),
      }))} value={onDelete} onChange={value => setDelete(value as OnDelete)} disabled={pending} />
      <Checkbox label={t('buildSpec.model.required')} checked={required} disabled={pending} onChange={event => {
        setRequired(event.target.checked)
        if (event.target.checked && onDelete === 'set_null') setDelete('restrict')
      }} />
      {error != null && !mapped && <BuildFailure error={error} />}
    </Form>
  </Dialog>
}
