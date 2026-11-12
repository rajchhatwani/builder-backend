import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { GoliveReport, GoliveStatus, OpsOverview } from '../../api/adminOps'
import { useUi } from '../../components/Ui'
import { LoadFailed } from '../../shell/behavior/ui'

const when = (t: string | null) => (t ? new Date(t).toLocaleString() : 'never')
const secs = (n: number | null) => (n === null ? 'n/a' : n % 3600 === 0 ? `${n / 3600} h` : n % 60 === 0 ? `${n / 60} min` : `${n} s`)
const STATUS_LABEL: Record<GoliveStatus, string> = { pass: 'Pass', fail: 'Fail', warn: 'Warning', skipped: 'Skipped' }
const errText = (e: unknown, fb: string) => (e instanceof Error ? e.message : fb)

export function GoliveResults({ report }: { report: GoliveReport }) {
  return (
    <div data-testid="golive-results">
      <p role="status" data-testid="golive-summary" data-ok={report.ok}>
        {report.ok ? 'Ready: no check failed.' : 'Not ready: at least one check failed.'} {report.passed} passed, {report.failed} failed, {report.warnings} {report.warnings === 1 ? 'warning' : 'warnings'}, {report.skipped} skipped. Ran {when(report.ran_at)}.
      </p>
      <table>
        <caption className="sr-only">Go-live checks</caption>
        <thead><tr><th scope="col">Check</th><th scope="col">Result</th><th scope="col">Why</th></tr></thead>
        <tbody>
          {report.checks.map((c) => (
            <tr key={c.check} data-testid="golive-row" data-status={c.status}>
              <th scope="row">{c.check}</th>
              <td data-testid="golive-status">{STATUS_LABEL[c.status]}</td>
              <td>{c.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Admin page "Operations": scheduler heartbeats, idle workspaces, report schedules, key provider, go-live checks.
 *  Reading is open to platform staff; running the go-live checks is for platform admins only (the button is hidden otherwise). */
export function OperationsPage({ readOnly }: { readOnly: boolean }) {
  const { toast } = useUi()
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [err, setErr] = useState('')
  const [ops, setOps] = useState<OpsOverview | null>(null)
  const [golive, setGolive] = useState<GoliveReport | null>(null)
  const [running, setRunning] = useState(false)
  const [runErr, setRunErr] = useState('')
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => { alive.current = false }
  }, [])

  const load = useCallback(() => {
    setState('loading')
    api.adminOperations().then((o) => {
      if (!alive.current) return
      setOps(o)
      setGolive(o.golive)
      setState('ready')
    }).catch((e) => {
      if (!alive.current) return
      setErr(errText(e, 'Could not load'))
      setState('error')
    })
  }, [])
  useEffect(load, [load])

  async function runGolive() {
    setRunning(true)
    setRunErr('')
    try {
      const r = await api.adminRunGolive()
      if (!alive.current) return
      setGolive(r)
      toast(r.ok ? 'Go-live checks finished: nothing failed.' : 'Go-live checks finished: something failed.', r.ok ? 'success' : 'danger')
    } catch (e) {
      if (alive.current) setRunErr(e instanceof ApiError && e.status === 403 ? 'Only platform admins can run the go-live checks.' : errText(e, 'Could not run the checks'))
    } finally {
      if (alive.current) setRunning(false)
    }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Operations</h1>
          <p>Background jobs, idle workspaces, scheduled reports, key provider and go-live checks.{readOnly && ' You can read this page; only platform admins can run the checks.'}</p>
        </div>
        <button className="outline small" onClick={load} disabled={state === 'loading'}>Refresh</button>
      </div>
      {state === 'loading' && <p className="empty-state" role="status">Loading…</p>}
      {state === 'error' && <LoadFailed what="operations" message={err} onRetry={load} />}
      {state === 'ready' && ops && (
        <>
          <section className="card" aria-labelledby="op-jobs-title" data-testid="scheduler">
            <h2 id="op-jobs-title">Scheduler</h2>
            <p className="muted">Checked {when(ops.generated_at)}. A job is stale when it has not run for three of its intervals.</p>
            {ops.scheduler.jobs.length === 0 ? (
              <p className="empty-state" data-testid="no-jobs">No background jobs have reported yet.</p>
            ) : (
              <table data-testid="job-table">
                <caption className="sr-only">Background jobs</caption>
                <thead><tr><th scope="col">Job</th><th scope="col">Every</th><th scope="col">Last run</th><th scope="col">Last result</th><th scope="col">Runs</th><th scope="col">Next expected</th><th scope="col">State</th></tr></thead>
                <tbody>
                  {ops.scheduler.jobs.map((j) => (
                    <tr key={j.job} data-testid="job-row" data-job={j.job} data-stale={j.stale}>
                      <th scope="row">{j.job}</th>
                      <td>{secs(j.interval_seconds)}</td>
                      <td>{when(j.last_run_at)}</td>
                      <td>{j.last_status === null ? 'No result yet' : j.last_status === 'ok' ? 'OK' : `Failed${j.last_error ? ` (${j.last_error})` : ''}`}</td>
                      <td>{j.runs}</td>
                      <td>{j.next_expected_at ? when(j.next_expected_at) : 'n/a'}</td>
                      <td data-testid="job-state">{j.stale ? 'Stale' : 'On time'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="card" aria-labelledby="op-idle-title" data-testid="idle">
            <h2 id="op-idle-title">Idle workspaces</h2>
            <p data-testid="idle-text">
              Idle for more than {ops.idle_workspaces.ttl_days} {ops.idle_workspaces.ttl_days === 1 ? 'day' : 'days'} are removed. {ops.idle_workspaces.live_workspaces} live, {ops.idle_workspaces.idle_past_ttl} past the limit.
            </p>
          </section>

          <section className="card" aria-labelledby="op-rep-title" data-testid="reports">
            <h2 id="op-rep-title">Scheduled reports</h2>
            <p data-testid="reports-text">
              {ops.reports.enabled_schedules} enabled, {ops.reports.disabled_schedules} disabled. Last run {when(ops.reports.last_run_at)}; next run {ops.reports.next_run_at ? when(ops.reports.next_run_at) : 'not scheduled'}.
            </p>
          </section>

          <section className="card" aria-labelledby="op-key-title" data-testid="key-provider">
            <h2 id="op-key-title">Key provider</h2>
            <p role="status" data-testid="key-state" data-healthy={ops.key_provider.healthy}>
              {ops.key_provider.healthy ? 'Healthy' : 'Not healthy'}: {ops.key_provider.kind} provider, {ops.key_provider.key_count} {ops.key_provider.key_count === 1 ? 'key' : 'keys'}, active key {ops.key_provider.active_key_id ?? 'none'}.
              {ops.key_provider.error && ` Error: ${ops.key_provider.error}.`}
            </p>
          </section>

          <section className="card" aria-labelledby="op-def-title" data-testid="usage-defaults">
            <h2 id="op-def-title">Default usage limits</h2>
            {ops.usage_defaults.length === 0 ? <p className="empty-state">No metered usage.</p> : (
              <table>
                <caption className="sr-only">Default usage limits</caption>
                <thead><tr><th scope="col">Metric</th><th scope="col">Unit</th><th scope="col">Period</th><th scope="col">Default limit</th></tr></thead>
                <tbody>
                  {ops.usage_defaults.map((d) => (
                    <tr key={d.metric}><th scope="row">{d.metric}</th><td>{d.unit}</td><td>{d.period === 'none' ? 'Total' : d.period === 'day' ? 'Per day' : 'Per month'}</td><td>{d.default_limit === null ? 'Unlimited' : d.default_limit}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="card" aria-labelledby="op-golive-title" data-testid="golive">
            <h2 id="op-golive-title">Go-live checks</h2>
            {!readOnly && (
              <button onClick={() => void runGolive()} disabled={running} data-testid="golive-run">{running ? 'Running…' : 'Run go-live checks'}</button>
            )}
            {runErr && <div role="alert" data-variant="danger" className="bh-alert" data-testid="golive-error">{runErr}</div>}
            {golive ? <GoliveResults report={golive} /> : <p className="empty-state">No results yet.</p>}
          </section>
        </>
      )}
    </>
  )
}
