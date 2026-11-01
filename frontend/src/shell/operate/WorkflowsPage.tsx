import { Issues, Kv, Off, ReadOnlyNotice, Scroll, SpecGate, Status } from '../connect/BlockUi'
import { issuesFor, retrySummary, workflowJobProblems } from '../connect/blockLogic'
import { useSpecBlocks } from '../connect/useSpecBlocks'

/** Operate > Workflows: durable multi-step processes (sagas) the spec declares, step by step. */
export function WorkflowsPage({ projectId }: { projectId: string }) {
  const { load, reload } = useSpecBlocks(projectId)
  return (
    <SpecGate title="Workflows" load={load} retry={reload}
      intro="Durable processes made of ordered steps. Each finished step is recorded, so a restart resumes where it stopped, and failures can undo earlier steps.">
      {({ spec, issues }) => {
        const w = spec.workflows
        const problems = workflowJobProblems(w, spec.jobs)
        return (
          <>
            <ReadOnlyNotice what="The workflows block" />
            <Issues issues={issuesFor(issues, 'workflows')} />
            {!w || !w.enabled ? (
              <Off what="Workflows">Declare a <code>workflows</code> block with <code>enabled: true</code>.</Off>
            ) : (
              <>
                {problems.length > 0 && (
                  <div role="alert" data-variant="warning" className="bh-conflict" data-testid="wf-problems">
                    <ul>{problems.map((p) => <li key={p}>{p}</li>)}</ul>
                  </div>
                )}
                <section aria-labelledby="wf-conf" className="card">
                  <h2 id="wf-conf">Runtime <Status on={w.enabled} /></h2>
                  <Kv items={[['Runner', `${w.runtime ?? 'postgres'} (built into the project's database)`], ['Runs at a time (per worker)', String(w.worker?.concurrency ?? 2)]]} />
                </section>
                {(w.workflows ?? []).length === 0 && <p className="muted" data-testid="wf-none">No workflows declared yet.</p>}
                {(w.workflows ?? []).length > 0 && <Scroll label="Declared workflows">
{(w.workflows ?? []).map((f, n) => (
                  <section key={f.name} aria-labelledby={`wf-${n}`} className="card" data-testid="wf-card">
                    <h2 id={`wf-${n}`}><code>{f.name}</code></h2>
                    <Kv items={[
                      ['Who may start and cancel runs', (f.roles ?? []).length ? (f.roles ?? []).join(', ') : 'nobody (add a role)'],
                      ['If a step fails', f.on_failure === 'fail' ? 'stop and leave finished steps as they are' : 'undo finished steps in reverse order'],
                      ['Whole run limit', `${f.timeout_seconds ?? 3600} s`],
                    ]} />
                    {(f.steps ?? []).length === 0 ? <p className="muted">No steps.</p> : (
                      <ol className="co-steps" aria-label={`Steps of ${f.name}`}>
                        {(f.steps ?? []).map((s) => (
                          <li key={s.name}>
                            <strong>{s.name}</strong> <span className="badge badge-muted">{s.kind === 'job' ? `job ${s.job ?? '?'}` : 'your code'}</span>
                            <small className="muted"> {retrySummary(s.retry)}; {s.timeout_seconds ?? 60} s{s.compensate === false ? '; no undo' : '; has an undo'}</small>
                          </li>
                        ))}
                      </ol>
                    )}
                  </section>
                ))}
</Scroll>}
              </>
            )}
          </>
        )
      }}
    </SpecGate>
  )
}
