import { createContext, useContext, useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  MAX_DEPTH, TOO_DEEP_MSG, csvToList, defaultFor, humanize, isShown, listToCsv, orderedKeys, pathKey, resolve, uiOf, validateValue,
  type Path, type Resolved,
} from './schemaLogic'
import type { JsonSchema, PathErrors } from './types'

export interface SchemaFormProps {
  schema: JsonSchema
  value: unknown
  onChange: (next: unknown) => void
  /** Backend validation messages by dotted JSON path. Shown verbatim, and they replace client hints for that path. */
  externalErrors?: PathErrors
  readOnly?: boolean
  /** Prefix for element ids; defaults to a generated one. */
  idPrefix?: string
}

interface Ctx {
  root: JsonSchema
  prefix: string
  readOnly: boolean
  messages: (p: Path) => string[]
  touch: (p: Path) => void
}
const FormCtx = createContext<Ctx>(null as unknown as Ctx)
const useForm = () => useContext(FormCtx)

const idOf = (c: Ctx, p: Path) => `${c.prefix}-${p.join('-') || 'form'}`

/** Renders a JSON Schema (Pydantic dialect) as an accessible form. Controlled: the parent owns `value`. */
export function SchemaForm({ schema, value, onChange, externalErrors, readOnly = false, idPrefix }: SchemaFormProps) {
  const auto = useId().replace(/:/g, '')
  const prefix = idPrefix ?? `sf${auto}`
  const [touched, setTouched] = useState<ReadonlySet<string>>(new Set())
  const client = useMemo(() => validateValue(schema, schema, value), [schema, value])

  const ctx = useMemo<Ctx>(
    () => ({
      root: schema,
      prefix,
      readOnly,
      messages: (p) => {
        const k = pathKey(p)
        const ext = externalErrors?.[k]
        if (ext?.length) return ext
        return touched.has(k) ? (client[k] ?? []) : []
      },
      touch: (p) => setTouched((t) => (t.has(pathKey(p)) ? t : new Set(t).add(pathKey(p)))),
    }),
    [schema, prefix, readOnly, externalErrors, touched, client],
  )

  const root = resolve(schema, schema)
  const total = Object.values(externalErrors ?? {}).reduce((n, m) => n + m.length, 0)
  const top = externalErrors?.[''] ?? []
  return (
    <FormCtx.Provider value={ctx}>
      <div data-schema-form>
        {total > 0 && (
          <div role="alert" data-variant="danger" className="bh-alert" data-testid="form-issue-summary">
            The backend validator found {total} {total === 1 ? 'problem' : 'problems'}. They are shown next to the fields below.
            {top.length > 0 && (
              <ul>
                {top.map((m, i) => (
                  <li key={i}>{m}</li>
                ))}
              </ul>
            )}
          </div>
        )}
        <Node schema={schema} path={[]} value={value} onChange={onChange} required label={root.title ?? ''} bare />
      </div>
    </FormCtx.Provider>
  )
}

interface NodeProps {
  schema: JsonSchema
  path: Path
  value: unknown
  onChange: (v: unknown) => void
  required: boolean
  label: string
  /** Root object: no fieldset/legend around it. */
  bare?: boolean
}

function Node(p: NodeProps) {
  const c = useForm()
  const s = resolve(c.root, p.schema)
  if (s.tooDeep || p.path.length > MAX_DEPTH) {
    return <div role="alert" data-variant="danger" className="bh-alert" data-testid="schema-too-deep" data-field-path={pathKey(p.path)}>{p.label ? `${p.label}: ` : ''}{TOO_DEEP_MSG}</div>
  }
  if (s.type === 'object' && s.properties) return <ObjectField {...p} s={s} />
  if (s.type === 'array') return <ArrayField {...p} s={s} />
  return <ScalarField {...p} s={s} />
}

function Help({ id, text }: { id: string; text?: string }) {
  return text ? (
    <small id={id} className="muted">
      {text}
    </small>
  ) : null
}

function ScalarField({ s, path, value, onChange, required, label, schema }: NodeProps & { s: Resolved }) {
  const c = useForm()
  const id = idOf(c, path)
  const msgs = c.messages(path)
  const bad = msgs.length > 0
  const helpText = uiOf(schema).help ?? uiOf(s).help ?? s.description
  const describedBy = [helpText && `${id}-help`, bad && `${id}-err`].filter(Boolean).join(' ') || undefined
  const common = {
    id,
    'aria-invalid': bad || undefined,
    'aria-describedby': describedBy,
    'aria-required': required && !s.nullable ? true : undefined,
    onBlur: () => c.touch(path),
  }
  const widget = uiOf(schema).widget ?? uiOf(s).widget
  let control: ReactNode
  if (s.enum) {
    control = (
      <select {...common} disabled={c.readOnly} value={value === null || value === undefined ? '' : String(value)}
        onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}>
        {(s.nullable || value === null || value === undefined) && <option value="">(not set)</option>}
        {s.enum.map((o) => <option key={String(o)} value={String(o)}>{String(o)}</option>)}
      </select>
    )
  } else if (s.type === 'boolean') {
    control = <input {...common} type="checkbox" disabled={c.readOnly} checked={value === true} onChange={(e) => onChange(e.target.checked)} />
  } else if (s.type === 'integer' || s.type === 'number') {
    control = (
      <input {...common} type="number" inputMode="decimal" step={s.type === 'integer' ? 1 : 'any'} readOnly={c.readOnly}
        value={typeof value === 'number' ? value : ''}
        onChange={(e) => onChange(e.target.value === '' ? (s.nullable ? null : undefined) : Number(e.target.value))} />
    )
  } else if (widget === 'textarea') {
    control = <textarea {...common} readOnly={c.readOnly} value={typeof value === 'string' ? value : ''} onChange={(e) => onChange(e.target.value)} />
  } else {
    control = (
      <input {...common} type="text" readOnly={c.readOnly} value={value === null || value === undefined ? '' : String(value)}
        onChange={(e) => onChange(e.target.value === '' && s.nullable ? null : e.target.value)} />
    )
  }
  return (
    <div className="bh-field" data-invalid={bad || undefined} data-field-path={pathKey(path)}>
      <label htmlFor={id}>
        {label}
        {required && !s.nullable && <span aria-hidden="true"> *</span>}
      </label>
      {control}
      <Help id={`${id}-help`} text={helpText} />
      {bad && (
        <small id={`${id}-err`} className="bh-error" data-testid="field-error">
          {msgs.join(' ')}
        </small>
      )}
    </div>
  )
}

function ObjectField({ s, path, value, onChange, label, bare, schema }: NodeProps & { s: Resolved }) {
  const c = useForm()
  const obj = (value && typeof value === 'object' ? value : {}) as Record<string, unknown>
  const props = s.properties!
  const keys = orderedKeys(s).filter((k) =>
    isShown(uiOf(props[k]), obj, (f) => (props[f] ? defaultFor(c.root, props[f]) : undefined)),
  )
  const set = (k: string, v: unknown) => onChange({ ...obj, [k]: v })

  // Consecutive scalars share a grid; nested objects and arrays take the full width.
  const blocks: { scalar: boolean; keys: string[] }[] = []
  for (const k of keys) {
    const t = resolve(c.root, props[k])
    const scalar = !(t.type === 'array' && uiOf(props[k]).widget !== 'csv') && !(t.type === 'object' && !!t.properties)
    const last = blocks[blocks.length - 1]
    if (last && last.scalar === scalar && scalar) last.keys.push(k)
    else blocks.push({ scalar, keys: [k] })
  }
  const body = blocks.map((b, i) => {
    const kids = b.keys.map((k) => (
      <Child key={k} k={k} parent={s} path={path} obj={obj} set={set} />
    ))
    return b.scalar ? <div className="bh-grid" key={i}>{kids}</div> : <div key={i}>{kids}</div>
  })
  if (bare) return <>{body}</>
  const id = idOf(c, path)
  const msgs = c.messages(path)
  const help = uiOf(schema).help ?? s.description
  return (
    <fieldset className="card bh-row" aria-describedby={[help && `${id}-help`, msgs.length && `${id}-err`].filter(Boolean).join(' ') || undefined} data-field-path={pathKey(path)}>
      <legend>{label}</legend>
      <Help id={`${id}-help`} text={help} />
      <GroupErrors id={`${id}-err`} msgs={msgs} />
      {body}
    </fieldset>
  )
}

function Child({ k, parent, path, obj, set }: { k: string; parent: Resolved; path: Path; obj: Record<string, unknown>; set: (k: string, v: unknown) => void }) {
  const child = parent.properties![k]
  // Property-level title wins; $ref'd definitions carry the class name, which is not a label.
  const auto = child.title === k.split('_').map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
  const label = uiOf(child).label ?? (child.title && !auto ? child.title : humanize(k))
  return (
    <Node
      schema={child}
      path={[...path, k]}
      value={obj[k]}
      onChange={(v) => set(k, v)}
      required={!!parent.required?.includes(k)}
      label={label}
    />
  )
}

function GroupErrors({ id, msgs }: { id: string; msgs: string[] }) {
  return msgs.length ? (
    <div id={id} role="alert" data-variant="danger" className="bh-alert" data-testid="group-error">
      {msgs.join(' ')}
    </div>
  ) : null
}

function ArrayField({ s, path, value, onChange, label, schema }: NodeProps & { s: Resolved }) {
  const c = useForm()
  const id = idOf(c, path)
  const msgs = c.messages(path)
  const hint = uiOf(schema)
  const arr = Array.isArray(value) ? value : []
  const focusNext = useRef<string | null>(null)

  useEffect(() => {
    const sel = focusNext.current
    if (!sel) return
    focusNext.current = null
    document.getElementById(`${id}-root`)?.querySelector<HTMLElement>(sel)?.focus()
  })

  if (hint.widget === 'csv') {
    const helpText = hint.help ?? s.description ?? 'Separate entries with commas'
    const bad = msgs.length > 0
    return (
      <div className="bh-field" data-invalid={bad || undefined} data-field-path={pathKey(path)}>
        <label htmlFor={id}>{label}</label>
        <input id={id} type="text" readOnly={c.readOnly} aria-invalid={bad || undefined}
          aria-describedby={[`${id}-help`, bad && `${id}-err`].filter(Boolean).join(' ')}
          onBlur={() => c.touch(path)}
          value={listToCsv(arr)} onChange={(e) => onChange(csvToList(e.target.value))} />
        <Help id={`${id}-help`} text={helpText} />
        {bad && <small id={`${id}-err`} className="bh-error" data-testid="field-error">{msgs.join(' ')}</small>}
      </div>
    )
  }

  const item = hint.itemLabel ?? `${label} item`
  const itemsSchema = s.items ?? {}
  const swap = (i: number, j: number) => {
    const next = [...arr]
    ;[next[i], next[j]] = [next[j], next[i]]
    focusNext.current = `[data-array-item="${j}"] [data-act="${j < i ? 'up' : 'down'}"]`
    onChange(next)
  }
  const add = () => {
    focusNext.current = `[data-array-item="${arr.length}"] input, [data-array-item="${arr.length}"] select`
    onChange([...arr, defaultFor(c.root, itemsSchema)])
  }
  const remove = (i: number) => {
    focusNext.current = arr.length > 1 ? `[data-array-item="${Math.min(i, arr.length - 2)}"] [data-act="remove"]` : '[data-act="add"]'
    onChange(arr.filter((_, k) => k !== i))
  }
  const help = hint.help ?? s.description
  return (
    <fieldset id={`${id}-root`} className="card bh-row" data-field-path={pathKey(path)}
      aria-describedby={[help && `${id}-help`, msgs.length && `${id}-err`].filter(Boolean).join(' ') || undefined}>
      <legend>{label}</legend>
      <Help id={`${id}-help`} text={help} />
      <GroupErrors id={`${id}-err`} msgs={msgs} />
      {arr.length === 0 && <p className="muted small-text">No {item.toLowerCase()} entries yet.</p>}
      {arr.map((it, i) => {
        const name = `${item} ${i + 1}`
        const sub = resolve(c.root, itemsSchema)
        const isObj = sub.type === 'object' && !!sub.properties
        return (
          <div key={i} data-array-item={i} className="bh-genrow" role="group" aria-label={name}
            aria-describedby={c.messages([...path, i]).length ? `${id}-${i}-err` : undefined}>
            <GroupErrors id={`${id}-${i}-err`} msgs={c.messages([...path, i])} />
            <Node
              schema={itemsSchema}
              path={[...path, i]}
              value={it}
              onChange={(v) => onChange(arr.map((x, k) => (k === i ? v : x)))}
              required
              label={name}
              bare={isObj}
            />
            {!c.readOnly && (
              <div className="bh-actions">
                <button type="button" className="outline small" data-act="up" aria-label={`Move ${name} up`} disabled={i === 0} onClick={() => swap(i, i - 1)}>Up</button>
                <button type="button" className="outline small" data-act="down" aria-label={`Move ${name} down`} disabled={i === arr.length - 1} onClick={() => swap(i, i + 1)}>Down</button>
                <button type="button" className="outline small" data-act="remove" aria-label={`Remove ${name}`} onClick={() => remove(i)}>Remove</button>
              </div>
            )}
          </div>
        )
      })}
      {!c.readOnly && (
        <button type="button" className="outline small" data-act="add" disabled={s.maxItems !== undefined && arr.length >= s.maxItems} onClick={add}>
          Add {item.toLowerCase()}
        </button>
      )}
    </fieldset>
  )
}
