import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { GenerationSummary, Preview, Project, ValidationIssue } from '../api/types'

interface GeneratePanelProps {
  project: Project
  /** Bumped by the parent whenever the model changed, to drop stale results. */
  modelVersion: number
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  return `${(bytes / 1024).toFixed(1)} KB`
}

/** The API reports validation problems either as a report or as spec_invalid error details. */
function issuesFrom(err: unknown): ValidationIssue[] | null {
  if (err instanceof ApiError && err.code === 'spec_invalid') return err.details as ValidationIssue[]
  return null
}

function IssueList({ issues }: { issues: ValidationIssue[] }) {
  return (
    <div className="table">
      <table>
        <thead>
          <tr>
            <th>Path</th>
            <th>Code</th>
            <th>Problem</th>
          </tr>
        </thead>
        <tbody>
          {issues.map((issue, i) => (
            <tr key={i}>
              <td>
                <code>{issue.path}</code>
              </td>
              <td>{issue.code}</td>
              <td>{issue.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function GeneratePanel({ project, modelVersion }: GeneratePanelProps) {
  const [issues, setIssues] = useState<ValidationIssue[] | null>(null)
  const [valid, setValid] = useState<boolean | null>(null)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [history, setHistory] = useState<GenerationSummary[]>([])
  const [busy, setBusy] = useState<'validate' | 'preview' | 'download' | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function loadHistory() {
    const page = await api.listGenerations(project.id, 20, 0)
    setHistory(page.items)
  }

  useEffect(() => {
    setIssues(null)
    setValid(null)
    setPreview(null)
    setError(null)
    loadHistory()
  }, [project.id, modelVersion])

  async function run(kind: 'validate' | 'preview' | 'download') {
    setBusy(kind)
    setError(null)
    try {
      if (kind === 'validate') {
        const report = await api.validateProject(project.id)
        setValid(report.valid)
        setIssues(report.issues)
      } else if (kind === 'preview') {
        setPreview(await api.previewGeneration(project.id))
        setValid(true)
        setIssues([])
      } else {
        const { blob, filename } = await api.downloadZip(project.id, `${project.slug}.zip`)
        const url = URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.download = filename
        link.click()
        URL.revokeObjectURL(url)
        setValid(true)
        setIssues([])
        await loadHistory()
      }
    } catch (err) {
      const found = issuesFrom(err)
      if (found) {
        setValid(false)
        setIssues(found)
        setPreview(null)
      } else {
        setError(err instanceof Error ? err.message : 'Something went wrong.')
      }
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      <div className="table-toolbar">
        <h3>Generate</h3>
        <div className="row-actions">
          <button className="outline small" disabled={busy !== null} onClick={() => run('validate')}>
            {busy === 'validate' ? 'Validating…' : 'Validate'}
          </button>
          <button className="outline small" disabled={busy !== null} onClick={() => run('preview')}>
            {busy === 'preview' ? 'Rendering…' : 'Preview files'}
          </button>
          <button className="small" disabled={busy !== null} onClick={() => run('download')}>
            {busy === 'download' ? 'Generating…' : 'Download zip'}
          </button>
        </div>
      </div>

      <div className="card" style={{ marginBlockEnd: 'var(--space-6)' }}>
        {error && (
          <div role="alert" data-variant="danger">
            {error}
          </div>
        )}
        {valid === true && !preview && (
          <div role="alert" data-variant="success">
            The model is valid.
          </div>
        )}
        {valid === false && issues && (
          <>
            <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-4)' }}>
              {issues.length} problem{issues.length === 1 ? '' : 's'} to fix before generating.
            </div>
            <IssueList issues={issues} />
          </>
        )}
        {preview && (
          <>
            <p>
              {preview.total_files} files, {formatBytes(preview.total_size)}. Spec hash{' '}
              <code>{preview.spec_hash.slice(0, 12)}</code>.
            </p>
            <div className="table" style={{ maxHeight: '20rem', overflow: 'auto' }}>
              <table>
                <tbody>
                  {preview.files.map((file) => (
                    <tr key={file.path}>
                      <td>
                        <code>{file.path}</code>
                      </td>
                      <td style={{ textAlign: 'end' }}>{formatBytes(file.size)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
        {valid === null && !error && !preview && (
          <p className="empty-state">
            Validate the model, preview the files, or download the generated project as a zip.
          </p>
        )}
      </div>

      <h3>Generation history</h3>
      <div className="card">
        {history.length === 0 ? (
          <p className="empty-state">No downloads yet.</p>
        ) : (
          <div className="table">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Spec hash</th>
                  <th>Files</th>
                  <th>Size</th>
                </tr>
              </thead>
              <tbody>
                {history.map((g) => (
                  <tr key={g.id}>
                    <td>{new Date(g.created_at).toLocaleString()}</td>
                    <td>
                      <code>{g.spec_hash.slice(0, 12)}</code>
                    </td>
                    <td>{g.file_count}</td>
                    <td>{formatBytes(g.total_size)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}
