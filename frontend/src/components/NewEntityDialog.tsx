import { useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import type { Entity } from '../api/types'
import { Modal } from './Modal'

interface NewEntityDialogProps {
  open: boolean
  projectId: string
  onClose: () => void
  onCreated: (entity: Entity) => void
}

export function NewEntityDialog({ open, projectId, onClose, onCreated }: NewEntityDialogProps) {
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  function reset() {
    setName('')
    setError(null)
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const entity = await api.createEntity(projectId, { name })
      reset()
      onCreated(entity)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong.')
    } finally {
      setSubmitting(false)
    }
  }

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
          <h3>New entity</h3>
          <p>PascalCase name, e.g. "Post". Table name and plural path are derived automatically.</p>
        </header>
        <div>
          {error && (
            <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-4)' }}>
              {error}
            </div>
          )}
          <label>
            Name
            <input
              required
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Post"
              pattern="^[A-Z][A-Za-z0-9]*$"
            />
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
          <button type="submit" disabled={submitting}>
            {submitting ? 'Creating…' : 'Create entity'}
          </button>
        </footer>
      </form>
    </Modal>
  )
}
