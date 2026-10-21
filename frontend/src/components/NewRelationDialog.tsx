import { useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import type { Entity, OnDelete, Relation, RelationKind } from '../api/types'
import { Modal } from './Modal'

interface NewRelationDialogProps {
  open: boolean
  projectId: string
  entities: Entity[]
  onClose: () => void
  onCreated: (relation: Relation) => void
}

export function NewRelationDialog({
  open,
  projectId,
  entities,
  onClose,
  onCreated,
}: NewRelationDialogProps) {
  const [kind, setKind] = useState<RelationKind>('one_to_many')
  const [fromEntityId, setFromEntityId] = useState('')
  const [toEntityId, setToEntityId] = useState('')
  const [fromName, setFromName] = useState('')
  const [toName, setToName] = useState('')
  const [onDelete, setOnDelete] = useState<OnDelete>('restrict')
  const [required, setRequired] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  function reset() {
    setKind('one_to_many')
    setFromEntityId('')
    setToEntityId('')
    setFromName('')
    setToName('')
    setOnDelete('restrict')
    setRequired(false)
    setError(null)
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const relation = await api.createRelation(projectId, {
        kind,
        from_entity_id: fromEntityId,
        to_entity_id: toEntityId,
        from_name: fromName,
        to_name: toName,
        on_delete: onDelete,
        required,
      })
      reset()
      onCreated(relation)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong.')
    } finally {
      setSubmitting(false)
    }
  }

  const canSubmit = entities.length >= 1

  return (
    <Modal
      open={open}
      onClose={() => {
        reset()
        onClose()
      }}
    >
      <form onSubmit={handleSubmit}>
        <header>
          <h3>New relation</h3>
          <p>Link two entities in this project. Names become the attribute on each side.</p>
        </header>
        <div>
          {error && (
            <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-4)' }}>
              {error}
            </div>
          )}
          {entities.length < 1 && (
            <div role="alert" data-variant="warning" style={{ marginBlockEnd: 'var(--space-4)' }}>
              Add at least one entity before creating a relation.
            </div>
          )}

          <label>
            Kind
            <select value={kind} onChange={(e) => setKind(e.target.value as RelationKind)}>
              <option value="one_to_many">One to many</option>
              <option value="many_to_many">Many to many</option>
              <option value="one_to_one">One to one</option>
            </select>
          </label>

          <div className="field-grid" style={{ marginBlockStart: 'var(--space-4)' }}>
            <label>
              From entity
              <select
                required
                value={fromEntityId}
                onChange={(e) => setFromEntityId(e.target.value)}
              >
                <option value="" disabled>
                  Select entity…
                </option>
                {entities.map((entity) => (
                  <option key={entity.id} value={entity.id}>
                    {entity.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              To entity
              <select required value={toEntityId} onChange={(e) => setToEntityId(e.target.value)}>
                <option value="" disabled>
                  Select entity…
                </option>
                {entities.map((entity) => (
                  <option key={entity.id} value={entity.id}>
                    {entity.name}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="field-grid" style={{ marginBlockStart: 'var(--space-4)' }}>
            <label>
              From name
              <input
                required
                value={fromName}
                onChange={(e) => setFromName(e.target.value)}
                placeholder="posts"
                pattern="^[a-z][a-z0-9_]*$"
              />
            </label>
            <label>
              To name
              <input
                required
                value={toName}
                onChange={(e) => setToName(e.target.value)}
                placeholder="author"
                pattern="^[a-z][a-z0-9_]*$"
              />
            </label>
          </div>

          <label style={{ marginBlockStart: 'var(--space-4)' }}>
            On delete
            <select value={onDelete} onChange={(e) => setOnDelete(e.target.value as OnDelete)}>
              <option value="restrict">Restrict</option>
              <option value="cascade">Cascade</option>
              <option value="set_null">Set null</option>
            </select>
          </label>

          <label style={{ marginBlockStart: 'var(--space-4)' }}>
            <input
              type="checkbox"
              checked={required}
              onChange={(e) => setRequired(e.target.checked)}
            />
            Required
          </label>
        </div>
        <footer>
          <button
            type="button"
            className="outline"
            onClick={() => {
              reset()
              onClose()
            }}
          >
            Cancel
          </button>
          <button type="submit" disabled={submitting || !canSubmit}>
            {submitting ? 'Creating…' : 'Create relation'}
          </button>
        </footer>
      </form>
    </Modal>
  )
}
