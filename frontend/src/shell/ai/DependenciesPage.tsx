import { useCallback, useEffect, useId, useState } from 'react'
import { api } from '../../api/client'
import type { DependencyPolicy, DependencyRequest, RegistryBlock, RegistryDep, RegistryHook } from '../../api/types'
import { ConfirmPrompt } from '../../components/ConfirmPrompt'
import { errMsg } from './useRunParam'

type Data = { policy: DependencyPolicy; requests: DependencyRequest[]; blocks: RegistryBlock[]; hooks: RegistryHook[]; deps: RegistryDep[] }
type Pending = { kind: 'approve' | 'deny' | 'revoke'; r: DependencyRequest }
const VERB = { approve: 'Approve', deny: 'Deny', revoke: 'Revoke' } as const

/** Dependency requests (approve / deny / revoke), plus the project's registry of blocks, hooks and locked dependencies. */
export function DependenciesPage({ projectId }: { projectId: string }) {
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState<Pending | null>(null)
  const [note, setNote] = useState('')
  const [form, setForm] = useState({ package: '', version: '', reason: '' })
  const ids = useId()

  const load = useCallback(async () => {
    try {
      const [policy, requests, blocks, hooks, deps] = await Promise.all([
        api.dependencyPolicy(projectId), api.listDependencyRequests(projectId), api.registryBlocks(projectId), api.registryHooks(projectId), api.registryDeps(projectId),
      ])
      setData({ policy, requests, blocks, hooks, deps }); setError('')
    } catch (e) { setError(errMsg(e)) }
  }, [projectId])
  useEffect(() => { void load() }, [load])

  const run = async (fn: () => Promise<unknown>): Promise<boolean> => {
    setBusy(true); setError('')
    try { await fn(); await load(); return true } catch (e) { setError(errMsg(e)); return false } finally { setBusy(false) }
  }
  const submit = async () => {
    if (await run(() => api.requestDependency(projectId, { package: form.package.trim(), version: form.version.trim(), reason: form.reason.trim() }))) setForm({ package: '', version: '', reason: '' })
  }
  const decide = async () => {
    if (!pending) return
    const { kind, r } = pending
    const ok = await run(() => kind === 'approve' ? api.approveDependency(projectId, r, note) : kind === 'deny' ? api.denyDependency(projectId, r.id, note) : api.revokeDependency(projectId, r.id, note))
    if (ok) { setPending(null); setNote('') }
  }
  const open = (kind: Pending['kind'], r: DependencyRequest) => { setPending({ kind, r }); setNote('') }
  const valid = form.package.trim() && form.version.trim() && form.reason.trim().length >= 3

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Dependencies</h1>
          <p>Extra packages your project's custom code may use. Each one needs an owner's approval before it can be installed.</p>
        </div>
      </div>
      {error && <p role="alert" data-testid="deps-error">{error}</p>}
      {!data && !error && <p className="empty-state">Loading…</p>}
      {data && (
        <>
          <section className="card" aria-labelledby={`${ids}-pol`} data-testid="deps-policy">
            <h2 id={`${ids}-pol`}>Policy</h2>
            <p data-testid="deps-pending-count">{data.policy.pending_requests} {data.policy.pending_requests === 1 ? 'request is' : 'requests are'} waiting for a decision.</p>
            <p>Allowed without approval: {data.policy.allow_list.length > 0 ? data.policy.allow_list.join(', ') : 'none'}.</p>
            {data.policy.approved.length > 0 && (
              <ul aria-label="Approved packages" data-testid="deps-approved">
                {data.policy.approved.map((a) => <li key={`${a.package}@${a.version}`}>{a.package} {a.version}{a.expires_at ? ` (until ${a.expires_at.slice(0, 10)})` : ''}</li>)}
              </ul>
            )}
          </section>

          <section className="card" aria-labelledby={`${ids}-req`}>
            <h2 id={`${ids}-req`}>Request a package</h2>
            <form onSubmit={(e) => { e.preventDefault(); void submit() }} aria-label="Request a package">
              <div className="field"><label htmlFor={`${ids}-p`}>Package</label><input id={`${ids}-p`} value={form.package} maxLength={100} onChange={(e) => setForm((f) => ({ ...f, package: e.target.value }))} data-testid="deps-package" /></div>
              <div className="field"><label htmlFor={`${ids}-v`}>Version</label><input id={`${ids}-v`} value={form.version} maxLength={50} onChange={(e) => setForm((f) => ({ ...f, version: e.target.value }))} data-testid="deps-version" /></div>
              <div className="field"><label htmlFor={`${ids}-r`}>Why do you need it?</label><input id={`${ids}-r`} value={form.reason} maxLength={2000} onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))} data-testid="deps-reason" /></div>
              <button type="submit" disabled={busy || !valid} data-testid="deps-request">Send request</button>
            </form>
          </section>

          <section className="card" aria-labelledby={`${ids}-list`}>
            <h2 id={`${ids}-list`}>Requests</h2>
            {data.requests.length === 0 ? <p className="empty-state" data-testid="deps-empty">No requests yet.</p> : (
              <div className="table">
                <table aria-label="Dependency requests" data-testid="deps-requests">
                  <thead><tr><th>Package</th><th>Why</th><th>Status</th><th>Actions</th></tr></thead>
                  <tbody>
                    {data.requests.map((r) => (
                      <tr key={r.id} data-testid="deps-row" data-status={r.status}>
                        <td>{r.package} {r.version}</td>
                        <td>{r.reason}{r.decision_note && <small className="muted"> Note: {r.decision_note}</small>}</td>
                        <td data-testid="deps-status">{r.status}</td>
                        <td>
                          {r.status === 'pending' && <>
                            <button className="small" disabled={busy} onClick={() => open('approve', r)} data-testid="deps-approve" aria-label={`Approve ${r.package} ${r.version}`}>Approve</button>{' '}
                            <button className="outline small" disabled={busy} onClick={() => open('deny', r)} data-testid="deps-deny" aria-label={`Deny ${r.package} ${r.version}`}>Deny</button>
                          </>}
                          {r.status === 'approved' && <button className="outline small" disabled={busy} onClick={() => open('revoke', r)} data-testid="deps-revoke" aria-label={`Revoke ${r.package} ${r.version}`}>Revoke</button>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {pending && (
              <ConfirmPrompt testId="deps-confirm" title={`${VERB[pending.kind]} ${pending.r.package} ${pending.r.version}?`} confirmLabel={VERB[pending.kind]} busy={busy} onConfirm={() => void decide()} onCancel={() => setPending(null)}>
                <p>{pending.kind === 'approve' ? `You are approving exactly ${pending.r.package} ${pending.r.version}${pending.r.hashes.length ? ` with ${pending.r.hashes.length} pinned hash(es)` : ''}.` : pending.kind === 'deny' ? 'The request is closed and the package cannot be used.' : 'The package can no longer be installed.'}</p>
                <label htmlFor={`${ids}-note`}>Note (optional)</label>{' '}
                <input id={`${ids}-note`} value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} data-testid="deps-note" />
              </ConfirmPrompt>
            )}
          </section>

          <section className="card" aria-labelledby={`${ids}-reg`} data-testid="deps-registry">
            <h2 id={`${ids}-reg`}>Registry</h2>
            <h3>Locked dependencies</h3>
            {data.deps.length === 0 ? <p className="empty-state">None recorded.</p> : <ul aria-label="Locked dependencies" data-testid="registry-deps">{data.deps.map((d) => <li key={d.id}>{d.package} {d.version} <code>{d.hash.slice(0, 16)}</code></li>)}</ul>}
            <h3>Hooks</h3>
            {data.hooks.length === 0 ? <p className="empty-state">None recorded.</p> : (
              <ul aria-label="Hooks" data-testid="registry-hooks">
                {data.hooks.map((h) => (
                  <li key={h.id} data-testid="registry-hook" data-approved={h.approved_by !== null}>
                    {h.hook_name} <small className="muted">by {h.author}, <code>{h.content_hash.slice(0, 12)}</code></small>{' '}
                    {h.approved_by ? <span className="badge badge-muted">approved</span> : <button className="outline small" disabled={busy} onClick={() => void run(() => api.approveRegistryHook(projectId, h.id))} data-testid="registry-hook-approve" aria-label={`Approve hook ${h.hook_name}`}>Approve hook</button>}
                  </li>
                ))}
              </ul>
            )}
            <h3>Block versions</h3>
            {data.blocks.length === 0 ? <p className="empty-state">None recorded.</p> : <p data-testid="registry-blocks">{data.blocks.length} block {data.blocks.length === 1 ? 'version' : 'versions'} recorded.</p>}
          </section>
        </>
      )}
    </>
  )
}
