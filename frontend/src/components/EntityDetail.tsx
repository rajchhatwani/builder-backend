import { useEffect, useMemo, useState, type FormEvent } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { api, ApiError } from '../api/client'
import type { Entity, EntityOptions, Field } from '../api/types'
import { DataTable } from './DataTable'
import { FieldDialog } from './FieldDialog'
import { useUi } from './Ui'

const OPERATIONS = ['list', 'get', 'head', 'create', 'replace', 'update', 'delete'] as const
const AUTO_FIELDS = ['id', 'created_at', 'updated_at']

interface EntityDetailProps {
  entity: Entity
  /** Called after anything changed so the parent can refresh its entity list. */
  onChanged: () => void
}

function toggle(list: string[], value: string, on: boolean): string[] {
  const without = list.filter((v) => v !== value)
  return on ? [...without, value] : without
}

export function EntityDetail({ entity, onChanged }: EntityDetailProps) {
  const { confirm, toast } = useUi()
  const [fields, setFields] = useState<Field[]>([])
  const [loading, setLoading] = useState(true)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<Field | null>(null)

  const [tableName, setTableName] = useState(entity.table_name)
  const [pluralPath, setPluralPath] = useState(entity.plural_path)
  const [options, setOptions] = useState<EntityOptions>(entity.options)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)

  async function loadFields() {
    setLoading(true)
    const page = await api.listFields(entity.id, 200, 0)
    setFields(page.items)
    setLoading(false)
  }

  useEffect(() => {
    loadFields()
    setTableName(entity.table_name)
    setPluralPath(entity.plural_path)
    setOptions(entity.options)
    setMessage(null)
  }, [entity.id])

  async function handleDelete(field: Field) {
    if (!(await confirm({ title: `Delete field "${field.name}"?`, confirmLabel: 'Delete', danger: true }))) return
    api.deleteField(field.id).then(() => {
      loadFields()
      onChanged()
    })
  }

  const columns = useMemo<ColumnDef<Field>[]>(
    () => [
      { accessorKey: 'name', header: 'Name' },
      { accessorKey: 'type', header: 'Type' },
      { id: 'required', header: 'Required', cell: ({ row }) => (row.original.required ? 'yes' : '') },
      { id: 'unique', header: 'Unique', cell: ({ row }) => (row.original.unique ? 'yes' : '') },
      { id: 'indexed', header: 'Indexed', cell: ({ row }) => (row.original.indexed ? 'yes' : '') },
      {
        id: 'details',
        header: 'Details',
        enableSorting: false,
        cell: ({ row }) => {
          const f = row.original
          const parts: string[] = []
          if (f.max_length) parts.push(`max ${f.max_length} chars`)
          if (f.min_value !== null) parts.push(`min ${f.min_value}`)
          if (f.max_value !== null) parts.push(`max ${f.max_value}`)
          if (f.enum_values) parts.push(f.enum_values.join(' | '))
          if (f.default !== null && f.default !== undefined) parts.push(`default ${JSON.stringify(f.default)}`)
          return parts.join(', ')
        },
      },
      {
        id: 'actions',
        header: '',
        enableSorting: false,
        cell: ({ row }) => (
          <div className="row-actions">
            <button
              className="outline small"
              onClick={() => {
                setEditing(row.original)
                setDialogOpen(true)
              }}
            >
              Edit
            </button>
            <button className="outline small" data-variant="danger" onClick={() => handleDelete(row.original)}>
              Delete
            </button>
          </div>
        ),
      },
    ],
    [],
  )

  async function handleSave(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setMessage(null)
    try {
      await api.updateEntity(entity.id, {
        table_name: tableName,
        plural_path: pluralPath,
        options,
      })
      setMessage(null)
      toast('Options saved.')
      onChanged()
    } catch (err) {
      const text =
        err instanceof ApiError && err.status === 409
          ? 'Table name or plural path is already used by another entity.'
          : err instanceof Error
            ? err.message
            : 'Something went wrong.'
      setMessage({ ok: false, text })
    } finally {
      setSaving(false)
    }
  }

  function fieldPicker(label: string, key: 'filterable' | 'sortable' | 'searchable', names: string[]) {
    return (
      <fieldset>
        <legend>{label}</legend>
        {names.map((name) => (
          <label key={name} style={{ display: 'inline-block', marginInlineEnd: 'var(--space-4)' }}>
            <input
              type="checkbox"
              checked={options[key].includes(name)}
              onChange={(e) => setOptions({ ...options, [key]: toggle(options[key], name, e.target.checked) })}
            />{' '}
            {name}
          </label>
        ))}
      </fieldset>
    )
  }

  const textFields = fields.filter((f) => f.type === 'string' || f.type === 'text').map((f) => f.name)
  const scalarFields = [...AUTO_FIELDS, ...fields.filter((f) => f.type !== 'json').map((f) => f.name)]

  return (
    <>
      <div className="page-header compact">
        <div>
          <h2>{entity.name}</h2>
          <p>
            Table <code>{entity.table_name}</code> &middot; served at <code>/{entity.plural_path}</code>
          </p>
        </div>
        <button
          onClick={() => {
            setEditing(null)
            setDialogOpen(true)
          }}
        >
          New field
        </button>
      </div>

      <h3>Fields</h3>
      <div className="card" style={{ marginBlockEnd: 'var(--space-6)' }}>
        {loading ? (
          <p className="empty-state">Loading…</p>
        ) : (
          <DataTable columns={columns} data={fields} emptyMessage="No fields yet. Add the first one." />
        )}
      </div>

      <h3>API options</h3>
      <form className="card" onSubmit={handleSave}>
        {message && (
          <div
            role="alert"
            data-variant={message.ok ? 'success' : 'danger'}
            style={{ marginBlockEnd: 'var(--space-4)' }}
          >
            {message.text}
          </div>
        )}
        <div className="field-grid">
          <label>
            Table name
            <input required value={tableName} onChange={(e) => setTableName(e.target.value)} />
          </label>
          <label>
            URL path
            <input required value={pluralPath} onChange={(e) => setPluralPath(e.target.value)} />
          </label>
          <label>
            Default page size
            <input
              type="number"
              min={1}
              value={options.default_page_size}
              onChange={(e) => setOptions({ ...options, default_page_size: Number(e.target.value) })}
            />
          </label>
          <label>
            Max page size
            <input
              type="number"
              min={1}
              value={options.max_page_size}
              onChange={(e) => setOptions({ ...options, max_page_size: Number(e.target.value) })}
            />
          </label>
        </div>

        <fieldset>
          <legend>Operations</legend>
          {OPERATIONS.map((op) => (
            <label key={op} style={{ display: 'inline-block', marginInlineEnd: 'var(--space-4)' }}>
              <input
                type="checkbox"
                checked={options.operations.includes(op)}
                onChange={(e) =>
                  setOptions({ ...options, operations: toggle(options.operations, op, e.target.checked) })
                }
              />{' '}
              {op}
            </label>
          ))}
        </fieldset>
        {fieldPicker('Filterable (exact match)', 'filterable', scalarFields)}
        {fieldPicker('Sortable', 'sortable', scalarFields)}
        {fieldPicker('Searchable (text)', 'searchable', textFields)}
        <label>
          <input
            type="checkbox"
            checked={options.soft_delete}
            onChange={(e) => setOptions({ ...options, soft_delete: e.target.checked })}
          />{' '}
          Soft delete (DELETE sets <code>deleted_at</code>)
        </label>
        <button type="submit" disabled={saving}>
          {saving ? 'Saving…' : 'Save options'}
        </button>
      </form>

      <FieldDialog
        open={dialogOpen}
        entityId={entity.id}
        field={editing}
        onClose={() => setDialogOpen(false)}
        onSaved={() => {
          setDialogOpen(false)
          loadFields()
          onChanged()
        }}
      />
    </>
  )
}
