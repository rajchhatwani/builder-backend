import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { CoverageResult, CoverageRow } from '../../api/types'
import { OPERATIONS } from './policyModel'

const STATE_TEXT: Record<CoverageRow['state'], { mark: string; label: string }> = {
  open: { mark: '●', label: 'Allowed without conditions for someone' },
  conditional: { mark: '◐', label: 'Allowed only when a condition holds' },
  closed: { mark: '○', label: 'Nobody can do this' },
}

/** Entity × action grid showing which operations the policies can ever allow, and why. */
export function CoverageTab({ projectId, version }: { projectId: string; version: number }) {
  const [coverage, setCoverage] = useState<CoverageResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [picked, setPicked] = useState<CoverageRow | null>(null)

  useEffect(() => {
    setCoverage(null)
    setPicked(null)
    api
      .authorizationCoverage(projectId)
      .then((c) => {
        setCoverage(c)
        setError(null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Could not build the coverage matrix.'))
  }, [projectId, version])

  if (error) {
    return (
      <div role="alert" data-variant="danger">
        {error}
      </div>
    )
  }
  if (!coverage) return <p className="empty-state">Loading…</p>

  const entities = [...new Set(coverage.rows.map((r) => r.entity))]
  const byKey = new Map(coverage.rows.map((r) => [`${r.entity}.${r.op}`, r]))
  const closed = coverage.rows.filter((r) => r.state === 'closed')

  return (
    <div>
      <div className="card">
        <p className="muted small-text">
          {Object.values(STATE_TEXT)
            .map((s) => `${s.mark} ${s.label}`)
            .join('   ·   ')}
          . A deny policy can still block an operation shown as allowed.
        </p>
        <div style={{ overflowX: 'auto' }}>
          <table className="permission-matrix">
            <thead>
              <tr>
                <th>Entity</th>
                {OPERATIONS.map((op) => (
                  <th key={op}>{op}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {entities.map((entity) => (
                <tr key={entity}>
                  <td className="entity-name">{entity}</td>
                  {OPERATIONS.map((op) => {
                    const row = byKey.get(`${entity}.${op}`)
                    if (!row) return <td key={op} className="muted">–</td>
                    const text = STATE_TEXT[row.state]
                    return (
                      <td
                        key={op}
                        className="matrix-cell"
                        title={text.label}
                        tabIndex={0}
                        role="button"
                        aria-label={`${entity} ${op}: ${text.label}`}
                        onClick={() => setPicked(row)}
                        onKeyDown={(e) => e.key === 'Enter' && setPicked(row)}
                        style={row.deny.length > 0 ? { outline: '1px dashed var(--danger)' } : undefined}
                      >
                        {text.mark}
                        {row.deny.length > 0 ? ' ⊘' : ''}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {closed.length > 0 && (
          <p className="muted small-text" style={{ marginBlockStart: 'var(--space-3)' }}>
            {closed.length} operation{closed.length === 1 ? ' is' : 's are'} closed. If that is not what you want, add or attach an allow
            policy for {closed.slice(0, 3).map((r) => `${r.entity}.${r.op}`).join(', ')}
            {closed.length > 3 ? '…' : ''}.
          </p>
        )}
      </div>

      {picked && (
        <div className="card" style={{ marginBlockStart: 'var(--space-4)' }}>
          <strong>
            {picked.entity}.{picked.op}
          </strong>{' '}
          <span className="badge badge-outline">{STATE_TEXT[picked.state].label}</span>
          {picked.allow.length === 0 && picked.deny.length === 0 && (
            <p className="muted small-text">No policy mentions this operation.</p>
          )}
          {picked.allow.length > 0 && (
            <>
              <p style={{ marginBlock: 'var(--space-2) var(--space-1)' }}>Allowed by</p>
              <ul>
                {picked.allow.map((a) => (
                  <li key={`${a.policy}-${a.who}`}>
                    <strong>{a.policy}</strong> for {a.who} — {a.unconditional ? 'always' : `when ${a.condition}`}
                  </li>
                ))}
              </ul>
            </>
          )}
          {picked.deny.length > 0 && (
            <>
              <p style={{ marginBlock: 'var(--space-2) var(--space-1)' }}>Blocked by</p>
              <ul>
                {picked.deny.map((a) => (
                  <li key={`${a.policy}-${a.who}`}>
                    <strong>{a.policy}</strong> for {a.who} — {a.unconditional ? 'always' : `when ${a.condition}`}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  )
}
