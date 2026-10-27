import { useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import type { Organization } from '../api/types'
import { Modal } from './Modal'

/** Same rule as the backend: lowercase letters, digits and hyphens, starting with a letter. */
const SLUG_RE = /^[a-z][a-z0-9-]*$/

interface NewOrgDialogProps {
  open: boolean
  onClose: () => void
  onCreated: (org: Organization) => void
}

/** Creates a team organization; the signed-in user becomes its owner. */
export function NewOrgDialog({ open, onClose, onCreated }: NewOrgDialogProps) {
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const slugInvalid = slug !== '' && !SLUG_RE.test(slug)

  function close() {
    setName('')
    setSlug('')
    setError(null)
    onClose()
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const org = await api.createOrg({ name: name.trim(), slug: slug || undefined })
      setName('')
      setSlug('')
      onCreated(org)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Can't reach the server.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open={open} onClose={close}>
      <form onSubmit={submit}>
        <header>
          <h3>New organization</h3>
          <p>A shared space for a team: its own people, projects and plan. You become its owner.</p>
        </header>
        <div>
          {error && (
            <div role="alert" data-variant="danger">
              {error}
            </div>
          )}
          <label>
            Name
            <input required maxLength={100} autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Acme Inc." />
          </label>
          <label>
            Address (optional)
            <input
              maxLength={100}
              value={slug}
              onChange={(e) => setSlug(e.target.value.toLowerCase())}
              placeholder="made from the name"
              aria-invalid={slugInvalid || undefined}
            />
            <small className="muted">
              {slugInvalid ? 'Use lowercase letters, digits and hyphens, starting with a letter.' : 'Used in links: #/org/<address>'}
            </small>
          </label>
        </div>
        <footer>
          <button type="button" className="outline" onClick={close}>
            Cancel
          </button>
          <button type="submit" disabled={busy || !name.trim() || slugInvalid}>
            {busy ? 'Creating…' : 'Create organization'}
          </button>
        </footer>
      </form>
    </Modal>
  )
}
