import { useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import type { Project } from '../api/types'
import { Modal } from './Modal'

interface NewProjectDialogProps {
  open: boolean
  onClose: () => void
  onCreated: (project: Project) => void
}

export function NewProjectDialog({ open, onClose, onCreated }: NewProjectDialogProps) {
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  function reset() {
    setName('')
    setSlug('')
    setError(null)
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const project = await api.createProject({ name, slug: slug || undefined })
      reset()
      onCreated(project)
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
          <h3>New project</h3>
          <p>A project groups entities, fields, and relations for one backend spec.</p>
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
              placeholder="Blog"
            />
          </label>
          <label style={{ marginBlockStart: 'var(--space-4)' }}>
            Slug (optional)
            <input
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              placeholder="blog"
              pattern="^[a-z][a-z0-9-]*$"
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
            {submitting ? 'Creating…' : 'Create project'}
          </button>
        </footer>
      </form>
    </Modal>
  )
}
