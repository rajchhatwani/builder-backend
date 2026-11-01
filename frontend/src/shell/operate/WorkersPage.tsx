import { Issues, Kv, Off, ReadOnlyNotice, SpecGate, Scroll } from '../connect/BlockUi'
import { issuesFor, placementLabel, totalConcurrency, unservedQueues } from '../connect/blockLogic'
import { useSpecBlocks } from '../connect/useSpecBlocks'

/** Operate > Workers: where worker processes run and which queues they serve; the queue backend. */
export function WorkersPage({ projectId }: { projectId: string }) {
  const { load, reload } = useSpecBlocks(projectId)
  return (
    <SpecGate title="Workers and queues" load={load} retry={reload}
      intro="Which worker groups run your background jobs, on which server, and the queue technology they read from.">
      {({ spec, issues }) => {
        const j = spec.jobs
        const unserved = unservedQueues(j)
        const backend = j?.queue?.backend ?? 'postgres'
        return (
          <>
            <ReadOnlyNotice what="Worker placement" />
            <Issues issues={issuesFor(issues, 'jobs.worker_groups', 'jobs.queue')} />
            {!j || !j.enabled ? (
              <Off what="Background jobs">Worker groups belong to the <code>jobs</code> block.</Off>
            ) : (
              <>
                {unserved.length > 0 && (
                  <div role="alert" data-variant="warning" className="bh-conflict" data-testid="workers-unserved">
                    No worker group serves {unserved.length === 1 ? 'the queue' : 'the queues'} {unserved.join(', ')}: jobs on {unserved.length === 1 ? 'it' : 'them'} would wait forever.
                  </div>
                )}
                <section aria-labelledby="wk-groups" className="card">
                  <h2 id="wk-groups">Worker groups</h2>
                  {(j.worker_groups ?? []).length === 0 ? <p className="muted" data-testid="workers-none">No worker groups declared.</p> : (
                    <Scroll label="Declared worker groups"><table className="bh-items" data-testid="workers-table">
                      <caption>Declared worker groups</caption>
                      <thead><tr><th scope="col">Group</th><th scope="col">Queues</th><th scope="col">Jobs at a time (per process)</th><th scope="col">Placement</th></tr></thead>
                      <tbody>
                        {(j.worker_groups ?? []).map((g) => (
                          <tr key={g.name}>
                            <td><code>{g.name}</code></td><td>{(g.queues ?? ['default']).join(', ')}</td><td>{g.concurrency ?? 4}</td><td>{placementLabel(g.placement)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table></Scroll>
                  )}
                  <Kv items={[['Slots across groups', String(totalConcurrency(j))]]} />
                </section>
                <section aria-labelledby="wk-advisor" className="card" data-testid="queue-advisor">
                  <h2 id="wk-advisor">Queue technology</h2>
                  <p>This project uses <strong>{backend}</strong>{backend === 'postgres' ? ' (the app’s own database, no extra service)' : ''}.</p>
                  {backend !== 'postgres' && <p role="note" className="muted">Only Postgres is implemented today; the validator refuses other backends.</p>}
                  <p className="muted">The queue advisor (which technology fits your throughput, ordering and durability needs) runs in the backend
                    but has no builder endpoint yet, so its recommendation cannot be shown here. Postgres is the default and stays right below about 1000 jobs per second.</p>
                </section>
              </>
            )}
          </>
        )
      }}
    </SpecGate>
  )
}
