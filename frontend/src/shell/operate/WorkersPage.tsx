import { useEffect, useState } from 'react'
import { api, type AdvisorResult } from '../../api/client'
import { Issues, Kv, Off, SpecGate, Scroll } from '../connect/BlockUi'
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
            <p className="muted" data-testid="workers-edit-note">Worker groups are part of the jobs block: change them on the Jobs and schedules page.</p>
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
                  <AdvisorResultView projectId={projectId} />
                </section>
              </>
            )}
          </>
        )
      }}
    </SpecGate>
  )
}

const text = (v: unknown): string =>
  Array.isArray(v) ? v.map(text).join(', ') : v && typeof v === 'object' ? Object.entries(v).map(([k, x]) => `${k}: ${text(x)}`).join('; ') : String(v)

function AdviceBlock({ id, title, data }: { id: string; title: string; data: Record<string, unknown> | null | undefined }) {
  const rows = Object.entries(data ?? {})
  return (
    <div data-testid={id}>
      <h3>{title}</h3>
      {rows.length === 0 ? <p className="muted">No advice for this project yet.</p> : <Kv items={rows.map(([k, v]) => [k.replace(/_/g, ' '), text(v)])} />}
    </div>
  )
}

/** The backend queue/workflow advisor (api.getAdvisor; its route is ADVISOR_PATH in api/client.ts). */
export function AdvisorResultView({ projectId }: { projectId: string }) {
  const [state, setState] = useState<{ s: 'loading' } | { s: 'error'; message: string } | { s: 'ready'; r: AdvisorResult }>({ s: 'loading' })
  const [n, setN] = useState(0)
  useEffect(() => {
    let live = true
    setState({ s: 'loading' })
    api.getAdvisor(projectId)
      .then((r) => live && setState({ s: 'ready', r }))
      .catch((e: unknown) => live && setState({ s: 'error', message: e instanceof Error ? e.message : 'Could not load the advisor' }))
    return () => { live = false }
  }, [projectId, n])
  if (state.s === 'loading') return <p className="empty-state" role="status">Loading the advisor…</p>
  if (state.s === 'error') {
    return (
      <div role="alert" data-variant="danger" className="bh-alert" data-testid="advisor-error">
        Could not load the advisor: {state.message} <button className="small" onClick={() => setN(n + 1)}>Try again</button>
      </div>
    )
  }
  return (
    <>
      <AdviceBlock id="advisor-queue" title="Queue advice" data={state.r.queue} />
      <AdviceBlock id="advisor-workflow" title="Workflow advice" data={state.r.workflow} />
    </>
  )
}
