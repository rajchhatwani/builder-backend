import { useState } from 'react'
import { ApiError, api } from '../../api/client'
import type { MigrationPlanResponse } from '../../api/types'

/** Plans the database change from the last generation to the current spec (read-only on the server). */
export function MigrationPlanSection({ projectId }: { projectId: string }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<MigrationPlanResponse | null>(null)

  const run = async (acceptUnreadable = false) => {
    setBusy(true)
    setError(null)
    try {
      setResult(await api.migrationPlan(projectId, {}, acceptUnreadable))
    } catch (err) {
      setResult(null)
      setError(err instanceof ApiError || err instanceof Error ? err.message : 'The plan could not be made')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card" aria-labelledby="migplan-h" data-testid="migplan">
      <h2 id="migplan-h">Database migration plan</h2>
      <p>Work out which database changes the current spec needs compared with the last download. Nothing is changed.</p>
      <button onClick={() => void run()} disabled={busy} data-testid="migplan-run">
        {busy ? 'Planning…' : 'Plan the migration'}
      </button>
      {error && <p role="alert" data-testid="migplan-error">{error}</p>}
      {result && <PlanResult result={result} onAcceptUnreadable={() => void run(true)} busy={busy} />}
    </section>
  )
}

function PlanResult({ result, onAcceptUnreadable, busy }: { result: MigrationPlanResponse; onAcceptUnreadable: () => void; busy: boolean }) {
  const { plan } = result
  return (
    <div data-testid="migplan-result" aria-live="polite">
      {result.first_generation && <p data-testid="migplan-first">No earlier download exists, so everything is new.</p>}
      {result.old_snapshot_unusable === true && (
        <div role="alert" data-testid="migplan-unusable">
          <p>The saved copy of the last download cannot be read.</p>
          <button className="outline" onClick={onAcceptUnreadable} disabled={busy} data-testid="migplan-accept-unreadable">Plan against an empty baseline instead</button>
        </div>
      )}
      <p data-testid="migplan-summary">
        {plan.steps.length} {plan.steps.length === 1 ? 'step' : 'steps'}
        {plan.highest_safety ? `, riskiest: ${plan.highest_safety}` : ''}
        {plan.requires_backfill ? ', needs a backfill' : ''}
        {result.allow_destructive_required ? ', needs your confirmation to destroy data' : ''}.
      </p>
      {plan.steps.length === 0 ? (
        <p>No database changes needed.</p>
      ) : (
        <div className="table">
          <table aria-label="Migration steps" data-testid="migplan-steps">
            <thead>
              <tr><th>#</th><th>Step</th><th>Where</th><th>Safety</th><th>Why</th></tr>
            </thead>
            <tbody>
              {plan.steps.map((s) => (
                <tr key={s.seq} data-testid="migplan-step">
                  <td>{s.seq}</td>
                  <td>{s.kind}</td>
                  <td>{s.table}{s.field ? `.${s.field}` : ''}</td>
                  <td>{s.safety}</td>
                  <td>
                    {s.reason}
                    {s.suggested_action && <div>Suggested: {s.suggested_action}</div>}
                    {s.backfill_strategy && <div>Backfill: {s.backfill_strategy}</div>}
                    {s.sql_hint && <pre><code>{s.sql_hint}</code></pre>}
                    {s.note && <div>{s.note}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {plan.ignored_sections.length > 0 && <p data-testid="migplan-ignored">Not covered by the plan: {plan.ignored_sections.join(', ')}.</p>}
      {result.text && (
        <details>
          <summary>Plain-text version</summary>
          <pre data-testid="migplan-text">{result.text}</pre>
        </details>
      )}
    </div>
  )
}
