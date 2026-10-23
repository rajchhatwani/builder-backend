import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { ValidationIssue } from '../api/types'
import { IssueList } from './GeneratePanel'

interface AuthChecksProps {
  projectId: string
  /** Changing this re-runs the check (the parent bumps it when the user switches tabs). */
  checkKey: string
}

/** Runs the project's validation and shows what is wrong with the auth settings, in place. */
export function AuthChecks({ projectId, checkKey }: AuthChecksProps) {
  const [issues, setIssues] = useState<ValidationIssue[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function check() {
    setBusy(true)
    setError(null)
    try {
      setIssues((await api.validateProject(projectId)).issues)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not validate the project.')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    check()
  }, [projectId, checkKey])

  const authIssues = (issues ?? []).filter((i) => i.path === 'auth' || i.path.startsWith('auth.'))
  const otherCount = (issues?.length ?? 0) - authIssues.length

  return (
    <div className="card" style={{ marginBlockEnd: 'var(--space-4)' }}>
      <div className="table-toolbar">
        <strong>Checks</strong>
        <button className="outline small" disabled={busy} onClick={check}>
          {busy ? 'Checking…' : 'Check again'}
        </button>
      </div>
      {error && (
        <div role="alert" data-variant="danger">
          {error}
        </div>
      )}
      {issues && authIssues.length === 0 && !error && (
        <div role="alert" data-variant="success">
          The auth settings are consistent and can be generated.
          {otherCount > 0 && ` (${otherCount} other problem${otherCount === 1 ? '' : 's'} in the schema.)`}
        </div>
      )}
      {authIssues.length > 0 && (
        <>
          <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-4)' }}>
            {authIssues.length} auth problem{authIssues.length === 1 ? '' : 's'} to fix before generating.
          </div>
          <IssueList issues={authIssues} />
        </>
      )}
    </div>
  )
}
