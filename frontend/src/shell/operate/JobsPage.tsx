import { Issues, Kv, Off, ReadOnlyNotice, SpecGate, Status, Scroll } from '../connect/BlockUi'
import { danglingSchedules, issuesFor, retrySummary } from '../connect/blockLogic'
import { useSpecBlocks } from '../connect/useSpecBlocks'

/** Operate > Jobs and schedules: what the spec declares (job kinds, retries, cron schedules). */
export function JobsPage({ projectId }: { projectId: string }) {
  const { load, reload } = useSpecBlocks(projectId)
  return (
    <SpecGate title="Jobs and schedules" load={load} retry={reload}
      intro="Background work your project runs: job kinds with retries, and schedules that start them on a cron.">
      {({ spec, issues }) => {
        const j = spec.jobs
        const dangling = danglingSchedules(j)
        return (
          <>
            <ReadOnlyNotice what="The jobs block" />
            <Issues issues={issuesFor(issues, 'jobs')} />
            {!j || !j.enabled ? (
              <Off what="Background jobs">Declare a <code>jobs</code> block with <code>enabled: true</code>.</Off>
            ) : (
              <>
                {dangling.length > 0 && (
                  <div role="alert" data-variant="warning" className="bh-conflict" data-testid="jobs-dangling">
                    Schedules that point at a job that is not declared: {dangling.join(', ')}.
                  </div>
                )}
                <section aria-labelledby="jb-jobs" className="card">
                  <h2 id="jb-jobs">Jobs <Status on={j.enabled} /></h2>
                  {(j.jobs ?? []).length === 0 ? <p className="muted" data-testid="jobs-none">No jobs declared yet.</p> : (
                    <Scroll label="Declared jobs"><table className="bh-items" data-testid="jobs-table">
                      <caption>Declared jobs</caption>
                      <thead><tr><th scope="col">Job</th><th scope="col">Queue</th><th scope="col">Handler</th><th scope="col">Retries</th><th scope="col">Time limit</th></tr></thead>
                      <tbody>
                        {(j.jobs ?? []).map((x) => (
                          <tr key={x.name}>
                            <td><code>{x.name}</code></td><td>{x.queue ?? 'default'}</td><td><code>{x.handler}</code></td>
                            <td>{retrySummary(x.retry)}</td><td>{x.timeout_seconds ?? 300} s</td>
                          </tr>
                        ))}
                      </tbody>
                    </table></Scroll>
                  )}
                  <p className="muted">Handlers are functions you write in <code>app/hooks/jobs.py</code>; the platform generates the registry and a stub.</p>
                </section>
                <section aria-labelledby="jb-sched" className="card">
                  <h2 id="jb-sched">Schedules</h2>
                  {(j.schedules ?? []).length === 0 ? <p className="muted" data-testid="sched-none">No schedules declared.</p> : (
                    <Scroll label="Declared schedules"><table className="bh-items" data-testid="sched-table">
                      <caption>Declared schedules</caption>
                      <thead><tr><th scope="col">Schedule</th><th scope="col">Job</th><th scope="col">Cron</th><th scope="col">Time zone</th><th scope="col">State</th><th scope="col">If ticks were missed</th></tr></thead>
                      <tbody>
                        {(j.schedules ?? []).map((s) => (
                          <tr key={s.name}>
                            <td><code>{s.name}</code></td><td><code>{s.job}</code></td><td><code>{s.cron}</code></td><td>{s.timezone ?? 'UTC'}</td>
                            <td>{s.enabled === false ? 'Paused' : 'Active'}</td>
                            <td>{s.missed === 'skip' ? 'Skip them' : 'Run the latest missed tick once'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table></Scroll>
                  )}
                  <Kv items={[['Exactly one job per tick', 'however many worker processes run']]} />
                </section>
              </>
            )}
          </>
        )
      }}
    </SpecGate>
  )
}
