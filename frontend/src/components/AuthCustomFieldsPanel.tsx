import { useState, useEffect, useMemo, type FormEvent } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { api, ApiError } from '../api/client'
import type { AuthCustomField, AuthCustomFieldCreate, AuthCustomFieldType } from '../api/types'
import { DataTable } from './DataTable'
import { Modal } from './Modal'

const STRING_LIKE: AuthCustomFieldType[] = ['string', 'text', 'email', 'phone', 'url']
const NUMERIC: AuthCustomFieldType[] = ['integer', 'float']
const FIELD_TYPES: AuthCustomFieldType[] = [
  'string',
  'text',
  'integer',
  'float',
  'boolean',
  'date',
  'datetime',
  'email',
  'phone',
  'url',
  'enum',
]

export interface AuthCustomFieldsPanelProps {
  projectId: string
}

function toNumberOrNull(text: string): number | null {
  const trimmed = text.trim()
  if (trimmed === '') return null
  const num = Number(trimmed)
  return Number.isNaN(num) ? null : num
}

export function AuthCustomFieldsPanel({ projectId }: AuthCustomFieldsPanelProps) {
  const [fields, setFields] = useState<AuthCustomField[]>([])
  const [loading, setLoading] = useState(true)

  // Modal dialog state
  const [modalOpen, setModalOpen] = useState(false)
  const [editingField, setEditingField] = useState<AuthCustomField | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Form field states
  const [name, setName] = useState('')
  const [label, setLabel] = useState('')
  const [type, setType] = useState<AuthCustomFieldType>('string')
  const [required, setRequired] = useState(false)
  const [unique, setUnique] = useState(false)
  const [indexed, setIndexed] = useState(false)
  const [minLength, setMinLength] = useState('')
  const [maxLength, setMaxLength] = useState('')
  const [minValue, setMinValue] = useState('')
  const [maxValue, setMaxValue] = useState('')
  const [enumValues, setEnumValues] = useState('')
  const [defaultValue, setDefaultValue] = useState('')
  const [position, setPosition] = useState('0')

  async function load() {
    setLoading(true)
    try {
      const page = await api.listAuthCustomFields(projectId, 200, 0)
      setFields(page.items)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [projectId])

  function close() {
    setModalOpen(false)
    setEditingField(null)
    setError(null)
  }

  function openCreate() {
    setEditingField(null)
    setName('')
    setLabel('')
    setType('string')
    setRequired(false)
    setUnique(false)
    setIndexed(false)
    setMinLength('')
    setMaxLength('')
    setMinValue('')
    setMaxValue('')
    setEnumValues('')
    setDefaultValue('')
    setPosition('0')
    setError(null)
    setModalOpen(true)
  }

  function openEdit(field: AuthCustomField) {
    setEditingField(field)
    setName(field.name)
    setLabel(field.label)
    setType(field.type)
    setRequired(field.required)
    setUnique(field.unique)
    setIndexed(field.indexed)
    setMinLength(field.min_length !== null && field.min_length !== undefined ? String(field.min_length) : '')
    setMaxLength(field.max_length !== null && field.max_length !== undefined ? String(field.max_length) : '')
    setMinValue(field.min_value !== null && field.min_value !== undefined ? String(field.min_value) : '')
    setMaxValue(field.max_value !== null && field.max_value !== undefined ? String(field.max_value) : '')
    setEnumValues(field.enum_values ? field.enum_values.join(', ') : '')
    setDefaultValue(field.default_value ?? '')
    setPosition(String(field.position ?? 0))
    setError(null)
    setModalOpen(true)
  }

  function handleDelete(field: AuthCustomField) {
    if (!window.confirm(`Delete field "${field.name}"?`)) return
    api.deleteAuthCustomField(field.id).then(load)
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)

    try {
      if (editingField) {
        await api.updateAuthCustomField(editingField.id, {
          label,
          required,
          unique,
          indexed,
          min_length: STRING_LIKE.includes(type) ? toNumberOrNull(minLength) : null,
          max_length: STRING_LIKE.includes(type) ? toNumberOrNull(maxLength) : null,
          min_value: NUMERIC.includes(type) ? toNumberOrNull(minValue) : null,
          max_value: NUMERIC.includes(type) ? toNumberOrNull(maxValue) : null,
          default_value: defaultValue.trim() === '' ? null : defaultValue,
          enum_values:
            type === 'enum'
              ? enumValues
                  .split(',')
                  .map((v) => v.trim())
                  .filter(Boolean)
              : null,
          position: toNumberOrNull(position) ?? 0,
        })
      } else {
        const data: AuthCustomFieldCreate = {
          name,
          label,
          type,
          required,
          unique,
          indexed,
          min_length: STRING_LIKE.includes(type) ? toNumberOrNull(minLength) : null,
          max_length: STRING_LIKE.includes(type) ? toNumberOrNull(maxLength) : null,
          min_value: NUMERIC.includes(type) ? toNumberOrNull(minValue) : null,
          max_value: NUMERIC.includes(type) ? toNumberOrNull(maxValue) : null,
          default_value: defaultValue.trim() === '' ? null : defaultValue,
          enum_values:
            type === 'enum'
              ? enumValues
                  .split(',')
                  .map((v) => v.trim())
                  .filter(Boolean)
              : null,
          position: toNumberOrNull(position) ?? 0,
        }
        await api.createAuthCustomField(projectId, data)
      }
      close()
      load()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError('A field with this name already exists.')
      } else {
        setError(err instanceof Error ? err.message : 'Something went wrong.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const columns = useMemo<ColumnDef<AuthCustomField>[]>(
    () => [
      { accessorKey: 'name', header: 'Name' },
      { accessorKey: 'label', header: 'Label' },
      { accessorKey: 'type', header: 'Type' },
      {
        id: 'required',
        header: 'Required',
        cell: ({ row }) => (row.original.required ? 'yes' : ''),
      },
      {
        id: 'unique',
        header: 'Unique',
        cell: ({ row }) => (row.original.unique ? 'yes' : ''),
      },
      {
        id: 'indexed',
        header: 'Indexed',
        cell: ({ row }) => (row.original.indexed ? 'yes' : ''),
      },
      { accessorKey: 'position', header: 'Position' },
      {
        id: 'details',
        header: 'Details',
        enableSorting: false,
        cell: ({ row }) => {
          const f = row.original
          const parts: string[] = []
          if (f.min_length !== null && f.min_length !== undefined) {
            parts.push(`min length ${f.min_length}`)
          }
          if (f.max_length !== null && f.max_length !== undefined) {
            parts.push(`max length ${f.max_length}`)
          }
          if (f.min_value !== null && f.min_value !== undefined) {
            parts.push(`min ${f.min_value}`)
          }
          if (f.max_value !== null && f.max_value !== undefined) {
            parts.push(`max ${f.max_value}`)
          }
          if (f.enum_values && f.enum_values.length > 0) {
            parts.push(f.enum_values.join(', '))
          }
          if (f.default_value !== null && f.default_value !== undefined && f.default_value !== '') {
            parts.push(`default ${f.default_value}`)
          }
          return parts.join(', ')
        },
      },
      {
        id: 'actions',
        header: '',
        enableSorting: false,
        cell: ({ row }) => (
          <div className="row-actions">
            <button className="outline small" onClick={() => openEdit(row.original)}>
              Edit
            </button>
            <button
              className="outline small"
              data-variant="danger"
              onClick={() => handleDelete(row.original)}
            >
              Delete
            </button>
          </div>
        ),
      },
    ],
    [],
  )

  return (
    <>
      <div className="table-toolbar">
        <h3>Custom registration fields</h3>
        <button className="outline small" onClick={openCreate}>
          New field
        </button>
      </div>

      <div className="card" style={{ marginBlockEnd: 'var(--space-6)' }}>
        {loading ? (
          <p className="empty-state">Loading…</p>
        ) : (
          <DataTable
            columns={columns}
            data={fields}
            emptyMessage="No custom fields yet."
          />
        )}
      </div>

      <Modal open={modalOpen} onClose={close}>
        <form onSubmit={handleSubmit}>
          <header>
            <h3>{editingField ? `Edit field "${editingField.name}"` : 'New field'}</h3>
          </header>
          <div>
            {error && (
              <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-4)' }}>
                {error}
              </div>
            )}
            <div className="field-grid">
              <label>
                Name
                <input
                  required
                  autoFocus={!editingField}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="phone_number"
                  pattern="^[a-z][a-z0-9_]*$"
                  readOnly={Boolean(editingField)}
                  disabled={Boolean(editingField)}
                />
              </label>
              <label>
                Label
                <input
                  required
                  autoFocus={Boolean(editingField)}
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  placeholder="Phone Number"
                />
              </label>
            </div>

            <label style={{ marginBlockStart: 'var(--space-4)' }}>
              Type
              <select
                value={type}
                disabled={Boolean(editingField)}
                onChange={(e) => setType(e.target.value as AuthCustomFieldType)}
              >
                {FIELD_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>

            <div className="field-grid" style={{ marginBlockStart: 'var(--space-4)' }}>
              <label>
                <input
                  type="checkbox"
                  checked={required}
                  onChange={(e) => setRequired(e.target.checked)}
                />{' '}
                Required
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={unique}
                  onChange={(e) => setUnique(e.target.checked)}
                />{' '}
                Unique
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={indexed}
                  onChange={(e) => setIndexed(e.target.checked)}
                />{' '}
                Indexed
              </label>
            </div>

            {STRING_LIKE.includes(type) && (
              <div className="field-grid" style={{ marginBlockStart: 'var(--space-4)' }}>
                <label>
                  Min length
                  <input
                    type="number"
                    min={0}
                    value={minLength}
                    onChange={(e) => setMinLength(e.target.value)}
                  />
                </label>
                <label>
                  Max length
                  <input
                    type="number"
                    min={1}
                    value={maxLength}
                    onChange={(e) => setMaxLength(e.target.value)}
                  />
                </label>
              </div>
            )}

            {NUMERIC.includes(type) && (
              <div className="field-grid" style={{ marginBlockStart: 'var(--space-4)' }}>
                <label>
                  Min value
                  <input
                    type="number"
                    step="any"
                    value={minValue}
                    onChange={(e) => setMinValue(e.target.value)}
                  />
                </label>
                <label>
                  Max value
                  <input
                    type="number"
                    step="any"
                    value={maxValue}
                    onChange={(e) => setMaxValue(e.target.value)}
                  />
                </label>
              </div>
            )}

            {type === 'enum' && (
              <label style={{ marginBlockStart: 'var(--space-4)' }}>
                Enum values
                <input
                  required
                  value={enumValues}
                  onChange={(e) => setEnumValues(e.target.value)}
                  placeholder="bronze, silver, gold"
                />
              </label>
            )}

            <label style={{ marginBlockStart: 'var(--space-4)' }}>
              Default value
              <input
                value={defaultValue}
                onChange={(e) => setDefaultValue(e.target.value)}
                placeholder="Optional"
              />
            </label>

            <label style={{ marginBlockStart: 'var(--space-4)' }}>
              Position
              <input
                type="number"
                min={0}
                value={position}
                onChange={(e) => setPosition(e.target.value)}
              />
            </label>
          </div>
          <footer>
            <button type="button" className="outline" onClick={close}>
              Cancel
            </button>
            <button type="submit" disabled={submitting}>
              {submitting ? 'Saving…' : editingField ? 'Save' : 'Create'}
            </button>
          </footer>
        </form>
      </Modal>
    </>
  )
}

export default AuthCustomFieldsPanel
