import { useId, useLayoutEffect, useRef, useState } from 'react'
import { defaultFor, humanize, isShown, orderedKeys, pathKey, resolve, uiOf, csvToList, listToCsv } from '../../forms/schemaLogic'
import type { ReactNode } from 'react'
import type { Path, Resolved } from '../../forms/schemaLogic'
import type { JsonSchema, PathErrors } from '../../forms/types'
import { useT } from '../i18n'
import { Alert, Button, Card, Checkbox, Field, Grid, Input, Row, Select, Stack, Textarea } from '../ui'
import type { FieldAttributes, SelectOption } from '../ui'
import { parseSchemaObject } from '../validators'
import { ConfirmDestructive } from './index'

export type SchemaFieldOverride = {
  path: Path; value: unknown; onChange: (value: unknown) => void; readOnly?: boolean; error?: string; id: string;
}

type SchemaProps = {
  schema: JsonSchema
  value: unknown
  onChange: (path: Path, value: unknown) => void
  onBlur?: (path: string) => void
  onStructure?: (path: string) => void
  errors?: PathErrors
  readOnly?: boolean
  options?: (path: Path) => SelectOption[] | undefined
  fieldOverride?: (props: SchemaFieldOverride) => ReactNode
  selectedRow?: (path: Path) => { index?: number; select: (index?: number) => void } | undefined
  confirmRemove?: boolean
  groupHeadings?: boolean
  rowDetail?: (path: Path, value: unknown) => ReactNode
  optionalLabel?: (label: string) => string
}

type NodeProps = SchemaProps & { node: JsonSchema; path: Path; name: string; required?: boolean; base: string }

export function SchemaFields(props: SchemaProps) {
  const base = useId()
  return <SchemaNode {...props} node={props.schema} path={[]} name="" base={base} />
}

function SchemaNode(props: NodeProps) {
  const { schema, node, path, name, base, value, onChange, onBlur, errors, readOnly, options } = props
  const t = useT()
  const shape = resolve(schema, node, path.length)
  const hint = uiOf(shape)
  const key = pathKey(path)
  const automaticTitle = name.split('_').map(part => part.charAt(0).toUpperCase() + part.slice(1)).join(' ')
  const title = node.title
  const label = t('schema.label', { label: hint.label ?? (title && title !== automaticTitle ? title : humanize(name)) })
  const messages = errors?.[key] ?? []
  const rowErrors = hint.widget === 'csv' || shape.type === 'object' && !shape.properties ? Object.entries(errors ?? {}).filter(([path]) => path.startsWith(key + '.'))
    .flatMap(([, issues]) => issues) : []
  const error = [...messages, ...rowErrors].join(' ')
  const id = base + '-' + key
  const write = (next: unknown) => onChange(path, next)
  const override = props.fieldOverride?.({ path, value, onChange: write, readOnly, error, id })
  if (override != null) return override
  if (shape.tooDeep) return <Alert tone="warning">{t('schema.deep')}</Alert>
  if (shape.type === 'object' && shape.properties) {
    const fields = shape.properties
    const current = value as Record<string, unknown> | null
    const children = <Grid>{orderedKeys(shape).filter(field =>
      isShown(uiOf(fields[field]), current ?? undefined, sibling => fields[sibling] && defaultFor(schema, fields[sibling])))
      .map(field => {
        const child = resolve(schema, fields[field])
        const wide = child.type === 'array' && uiOf(child).widget !== 'csv' || child.type === 'object' || uiOf(child).widget === 'textarea'
        return <div key={field} data-field-path={props.groupHeadings ? pathKey([...path, field]) : undefined} className={wide ? 'v2-schema-wide' : undefined}><SchemaNode {...props} node={fields[field]} path={[...path, field]}
          name={field} value={current?.[field]} required={shape.required?.includes(field)} /></div>
      })}</Grid>
    if (!path.length) return children
    const Heading = props.groupHeadings && path.length === 1 ? 'h2' : 'h3'
    return <Card role="group" aria-label={label}><Stack>
      <Heading>{label}</Heading>
      {shape.nullable && hint.optional && <Checkbox label={props.optionalLabel?.(label) ?? t('schema.include', { label })} checked={current != null} disabled={readOnly}
        onChange={event => write(event.target.checked ? defaultFor(schema, Object.assign({}, shape, { nullable: false, default: undefined })) : null)} />}
      {(!hint.optional || current != null) && children}
      {error && <Alert tone="danger">{t('schema.message', { message: error })}</Alert>}
    </Stack></Card>
  }
  if (shape.type === 'array' && hint.widget !== 'csv' && shape.items) {
    return <SchemaRows {...props} shape={shape} label={label} />
  }
  const optionList = options?.(path) ?? shape.enum?.map(choice => ({ value: String(choice), label: t('schema.option', { value: String(choice) }) }))
  const help = hint.help ?? shape.description
  return <Field id={id} label={shape.type !== 'boolean' ? label : undefined}
    hint={help && t('schema.message', { message: help })} error={error && t('schema.message', { message: error })}>
    {attrs => {
      if (shape.type === 'boolean') return <Checkbox {...attrs} label={label} checked={value === true} disabled={readOnly}
        onBlur={() => onBlur?.(key)} onChange={event => write(event.target.checked)} />
      if (optionList) {
        const selected = value == null || value === '' ? '' : String(value)
        const available = selected && !optionList.some(item => item.value === selected)
          ? [...optionList, { value: selected, label: t('schema.option', { value: selected }) }] : optionList
        return <Select options={shape.nullable ? [{ value: '__unset', label: t('schema.unset') }, ...available] : available}
          value={shape.nullable && value == null ? '__unset' : selected} placeholder={t('schema.unset')} disabled={readOnly} triggerProps={{ ...attrs, onBlur: () => onBlur?.(key) }}
          onValueChange={next => write(next === '__unset' ? null : next)} />
      }
      if (shape.type === 'object') return <SchemaText {...attrs} mode="json" value={value} readOnly={readOnly}
        onChange={write} onBlur={() => onBlur?.(key)} />
      if (hint.widget === 'csv') return <SchemaText {...attrs} mode="csv" value={value} readOnly={readOnly}
        onChange={write} onBlur={() => onBlur?.(key)} />
      const number = shape.type === 'integer' || shape.type === 'number'
      const input = {
        ...attrs, value: typeof value === 'number' || typeof value === 'string' ? value : '', readOnly,
        onBlur: () => onBlur?.(key),
        onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
          const text = event.target.value
          write(text === '' ? shape.nullable ? null : '' : number ? Number(text) : text)
        },
      }
      return hint.widget === 'textarea' ? <Textarea {...input} rows={4} /> :
        <Input {...input} type={number ? 'number' : 'text'} step={shape.type === 'number' ? 'any' : undefined} />
    }}
  </Field>
}

function SchemaText({ mode, value, onChange, onBlur, readOnly, ...attrs }: FieldAttributes & {
  mode: 'json' | 'csv'; value: unknown; onChange: (value: unknown) => void; onBlur: () => void; readOnly?: boolean
}) {
  const t = useT()
  const [raw, setRaw] = useState<string>()
  const [error, setError] = useState<string>()
  const invalidId = attrs.id + '-json'
  const input = {
    ...attrs, readOnly,
    'aria-invalid': error ? true as const : attrs['aria-invalid'],
    'data-json-invalid': error ? true : undefined,
    'aria-describedby': [attrs['aria-describedby'], error && invalidId].filter(Boolean).join(' ') || undefined,
    value: raw ?? (mode === 'csv' ? listToCsv(value) : JSON.stringify(value ?? {}, null, 2)),
    onBlur: () => { if (!error) setRaw(undefined); onBlur() },
    onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      const text = event.target.value
      setRaw(text)
      if (mode === 'csv') { onChange(csvToList(text)); return }
      const parsed = parseSchemaObject(text)
      setError(parsed.error)
      if (!parsed.error) onChange(parsed.value)
    },
  }
  return mode === 'csv' ? <Input {...input} /> : <Stack gap={1}><Textarea {...input} rows={4} />
    {error && <span id={invalidId} role="alert" className="v2-field-error">{t(error)}</span>}
  </Stack>
}

function SchemaRows({ shape, label, ...props }: NodeProps & { shape: Resolved; label: string }) {
  const t = useT()
  const { schema, path, value, onChange, onStructure, errors, readOnly, name } = props
  const items = Array.isArray(value) ? value : []
  const item = shape.items!
  const selection = props.selectedRow?.(path)
  const singular = uiOf(shape).itemLabel ?? resolve(schema, item).title ?? humanize(name)
  const error = errors?.[pathKey(path)]?.join(' ')
  const area = useRef<HTMLElement>(null)
  const focus = useRef<{ index: number; action: string } | null>(null)
  const [revision, setRevision] = useState(0)
  useLayoutEffect(() => {
    if (!focus.current) return
    const { index, action } = focus.current
    if (action === 'add' && selection && selection.index !== index) return
    focus.current = null
    const row = area.current?.querySelector('[data-schema-row="' + index + '"]')
    const target = action === 'add' ? row?.querySelector('input,textarea,[role="combobox"]') :
      row?.querySelector('[data-row-action="' + action + '"]:not(:disabled)') ?? row?.querySelector('[data-row-action="remove"]')
    ;(target as HTMLElement | null ?? area.current?.querySelector<HTMLElement>('[data-row-action="add"]'))?.focus()
  }, [items, selection])
  function change(next: unknown[], index: number, action: string) {
    focus.current = { index, action }
    setRevision(current => current + 1)
    onStructure?.(pathKey(path))
    onChange(path, next)
    selection?.select(index >= 0 && action !== 'remove' ? index : undefined)
  }
  function move(index: number, step: number) {
    const next = [...items]
    ;[next[index], next[index + step]] = [next[index + step], next[index]]
    change(next, index + step, step < 0 ? 'up' : 'down')
  }
  const Heading = props.groupHeadings && path.length === 1 ? 'h2' : 'h3'
  const RowHeading = props.groupHeadings && path.length === 1 ? 'h3' : 'h4'
  return <Card role="group" aria-label={label} ref={area}><Stack>
    <Heading>{label}</Heading>
    {error && <Alert tone="danger">{t('schema.message', { message: error })}</Alert>}
    {selection && !items.length && <p>{t('schema.emptyRows', { label })}</p>}
    {items.map((value, index) => {
      const expanded = !selection || selection.index === index
      const remove = () => change(items.filter((_, position) => position !== index), Math.min(index, items.length - 2), 'remove')
      const itemTitle = typeof value === 'object' && value !== null && 'name' in value && typeof value.name === 'string' ? value.name : ''
      const rowName = itemTitle && selection ? t('schema.rowName', { name: itemTitle }) : undefined
      const rowLabel = t('schema.row', { item: singular, index: index + 1 })
      return <Card key={index} role="group" aria-label={rowLabel} data-schema-row={index}><Stack>
        <Row>
          <RowHeading>{rowName || rowLabel}</RowHeading>
          {selection && <Button aria-expanded={expanded} onClick={() => selection.select(expanded ? undefined : index)}>
            {t(expanded ? 'schema.collapse' : 'schema.expand')}
          </Button>}
        </Row>
        {props.rowDetail?.(path, value)}
        {expanded && <SchemaNode {...props} key={revision} node={item} path={[...path, index]} name={singular} value={value} required />}
        {!readOnly && <Row>
          <Button data-row-action="up" aria-label={t('schema.moveUp', { label: rowLabel })} disabled={!index} onClick={() => move(index, -1)}>{t('schema.up')}</Button>
          <Button data-row-action="down" aria-label={t('schema.moveDown', { label: rowLabel })} disabled={index === items.length - 1} onClick={() => move(index, 1)}>{t('schema.down')}</Button>
          {props.confirmRemove ? <ConfirmDestructive
            trigger={<Button variant="danger" data-row-action="remove" aria-label={t('schema.removeRow', { label: rowLabel })}>{t('schema.remove')}</Button>}
            title={t('schema.removeTitle', { label: rowLabel })} description={t('schema.removeHelp')}
            action={t('schema.remove')} onConfirm={remove} /> :
            <Button data-row-action="remove" aria-label={t('schema.removeRow', { label: rowLabel })} onClick={remove}>{t('schema.remove')}</Button>}
        </Row>}
      </Stack></Card>
    })}
    {!readOnly && <Row><Button data-row-action="add" disabled={items.length >= (shape.maxItems ?? Infinity)}
      // Keep focus until activation so a blur error cannot move the button during a click.
      onMouseDown={event => event.preventDefault()}
      onClick={() => change([...items, defaultFor(schema, item)], items.length, 'add')}>{t('schema.add', { item: singular.toLowerCase() })}</Button></Row>}
  </Stack></Card>
}
