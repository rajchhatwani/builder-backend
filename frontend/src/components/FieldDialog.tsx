import { useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import type { Field, FieldInput, FieldType } from '../api/types'
import { Modal } from './Modal'

export const FIELD_TYPES: FieldType[] = [
  'string',
  'text',
  'integer',
  'bigint',
  'float',
  'decimal',
  'boolean',
  'date',
  'datetime',
  'uuid',
  'json',
  'enum',
]

const NUMERIC: FieldType[] = ['integer', 'bigint', 'float', 'decimal']

interface FieldDialogProps {
  open: boolean
  entityId: string
  /** When set the dialog edits this field, otherwise it creates a new one. */
  field: Field | null
  onClose: () => void
  onSaved: () => void
}

function defaultToText(value: unknown): string {
  if (value === null || value === undefined) return ''
  return typeof value === 'string' ? value : JSON.stringify(value)
}

/** Turns the text box into the JSON value the API expects for the field's type. */
function parseDefault(text: string, type: FieldType): unknown {
  const trimmed = text.trim()
  if (trimmed === '') return null
  switch (type) {
    case 'integer':
    case 'bigint':
    case 'float':
    case 'decimal': {
      const value = Number(trimmed)
      if (Number.isNaN(value)) throw new Error('Default must be a number.')
      return value
    }
    case 'boolean':
      if (trimmed !== 'true' && trimmed !== 'false') throw new Error('Default must be true or false.')
      return trimmed === 'true'
    case 'json':
      try {
        return JSON.parse(trimmed)
      } catch {
        throw new Error('Default must be valid JSON.')
      }
    default:
      return text
  }
}

function toNumberOrNull(text: string): number | null {
  return text.trim() === '' ? null : Number(text)
}

export function FieldDialog({ open, entityId, field, onClose, onSaved }: FieldDialogProps) {
  const [name, setName] = useState('')
  const [type, setType] = useState<FieldType>('string')
  const [required, setRequired] = useState(false)
  const [unique, setUnique] = useState(false)
  const [indexed, setIndexed] = useState(false)
  const [maxLength, setMaxLength] = useState('')
  const [minValue, setMinValue] = useState('')
  const [maxValue, setMaxValue] = useState('')
  const [enumValues, setEnumValues] = useState('')
  const [defaultText, setDefaultText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // Re-seed the form whenever the dialog opens for a (different) field.
  useEffect(() => {
    if (!open) return
    setName(field?.name ?? '')
    setType(field?.type ?? 'string')
    setRequired(field?.required ?? false)
    setUnique(field?.unique ?? false)
    setIndexed(field?.indexed ?? false)
    setMaxLength(field?.max_length?.toString() ?? '')
    setMinValue(field?.min_value?.toString() ?? '')
    setMaxValue(field?.max_value?.toString() ?? '')
    setEnumValues(field?.enum_values?.join(', ') ?? '')
    setDefaultText(defaultToText(field?.default))
    setError(null)
  }, [open, field])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const input: FieldInput = {
        name,
        type,
        required,
        unique,
        indexed,
        default: parseDefault(defaultText, type),
        max_length: type === 'string' ? toNumberOrNull(maxLength) : null,
        min_value: NUMERIC.includes(type) ? toNumberOrNull(minValue) : null,
        max_value: NUMERIC.includes(type) ? toNumberOrNull(maxValue) : null,
        enum_values:
          type === 'enum'
            ? enumValues
                .split(',')
                .map((v) => v.trim())
                .filter(Boolean)
            : null,
      }
      if (field) await api.updateField(field.id, input)
      else await api.createField(entityId, input)
      onSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
      if (err instanceof ApiError && err.status === 409) setError('A field with this name already exists.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose}>
      <form onSubmit={handleSubmit}>
        <header>
          <h3>{field ? `Edit field "${field.name}"` : 'New field'}</h3>
          <p>
            snake_case name. <code>id</code>, <code>created_at</code> and <code>updated_at</code> are
            added automatically.
          </p>
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
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="display_name"
                pattern="^[a-z][a-z0-9_]*$"
              />
            </label>
            <label>
              Type
              <select value={type} onChange={(e) => setType(e.target.value as FieldType)}>
                {FIELD_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="field-grid" style={{ marginBlockStart: 'var(--space-4)' }}>
            <label>
              <input type="checkbox" checked={required} onChange={(e) => setRequired(e.target.checked)} />{' '}
              Required
            </label>
            <label>
              <input type="checkbox" checked={unique} onChange={(e) => setUnique(e.target.checked)} />{' '}
              Unique
            </label>
            <label>
              <input type="checkbox" checked={indexed} onChange={(e) => setIndexed(e.target.checked)} />{' '}
              Indexed
            </label>
          </div>

          {type === 'string' && (
            <label style={{ marginBlockStart: 'var(--space-4)' }}>
              Max length (default 255)
              <input type="number" min={1} value={maxLength} onChange={(e) => setMaxLength(e.target.value)} />
            </label>
          )}
          {NUMERIC.includes(type) && (
            <div className="field-grid" style={{ marginBlockStart: 'var(--space-4)' }}>
              <label>
                Min value
                <input type="number" step="any" value={minValue} onChange={(e) => setMinValue(e.target.value)} />
              </label>
              <label>
                Max value
                <input type="number" step="any" value={maxValue} onChange={(e) => setMaxValue(e.target.value)} />
              </label>
            </div>
          )}
          {type === 'enum' && (
            <label style={{ marginBlockStart: 'var(--space-4)' }}>
              Values (comma separated)
              <input
                required
                value={enumValues}
                onChange={(e) => setEnumValues(e.target.value)}
                placeholder="draft, published, archived"
              />
            </label>
          )}
          <label style={{ marginBlockStart: 'var(--space-4)' }}>
            Default (optional{type === 'json' ? ', JSON' : type === 'boolean' ? ': true or false' : ''})
            <input value={defaultText} onChange={(e) => setDefaultText(e.target.value)} />
          </label>
        </div>
        <footer>
          <button type="button" className="outline" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" disabled={submitting}>
            {submitting ? 'Saving…' : field ? 'Save field' : 'Add field'}
          </button>
        </footer>
      </form>
    </Modal>
  )
}
