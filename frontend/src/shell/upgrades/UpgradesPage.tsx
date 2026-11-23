import { useCallback, useEffect, useRef, useState } from 'react'
import { api, saveBlob } from '../../api/client'
import type { Scorecard, ScorecardCheck, UpgradeProposalDetail, UpgradeProposalSummary } from '../../api/types'
import { applyCommand, eligibilityReason, groupChecks, patchFilename, readBlockChanges, readFiles, readMigrations, readSbom, shortDate, upgradeError } from './upgradeLogic'

type Load<T> = { s: 'loading' } | { s: 'error'; m: string } | { s: 'ok'; v: T }
const icon = (s: string) => (s === 'pass' ? '✓ ' : s === 'warn' ? '! ' : '✗ ')
const label = (s: string) => (s === 'pass' ? 'Pass' : s === 'warn' ? 'Warning' : 'Fail')

function FixAction({ check, projectId, busy, onOpenUpgrade }: { check: ScorecardCheck; projectId: string; busy: boolean; onOpenUpgrade: () => void }) {
  if (check.status === 'pass') return null
  switch (check.fix.action) {
    case 'open_upgrade':
      return <button type="button" disabled={busy} onClick={onOpenUpgrade} aria-label={`Create upgrade proposal to fix ${check.id}`} data-testid="fix-open-upgrade">Create upgrade proposal</button>
    case 'regenerate':
      return <a href={`#/p/${projectId}/generate`} data-testid="fix-regenerate">Regenerate and download the project</a>
    case 'redeclare_hook':
      return <a href={`#/p/${projectId}/hooks`} data-testid="fix-hook">Review the hooks and declare them again</a>
    default:
      return <small className="muted" data-testid="fix-none">No automatic fix. Read the detail and change the spec by hand.</small>
  }
}

function ScorecardSection({ projectId, busy, onOpenUpgrade, refresh }: { projectId: string; busy: boolean; onOpenUpgrade: () => void; refresh: number }) {
  const [load, setLoad] = useState<Load<Scorecard>>({ s: 'loading' })
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    let dead = false
    setLoad({ s: 'loading' })
    api.getScorecard(projectId).then((v) => { if (!dead) setLoad({ s: 'ok', v }) }, (e) => { if (!dead) setLoad({ s: 'error', m: upgradeError(e, 'Could not load the scorecard') }) })
    return () => { dead = true }
  }, [projectId, retry, refresh])
  if (load.s === 'loading') return <p role="status" className="empty-state">Loading scorecard…</p>
  if (load.s === 'error') return <div role="alert" data-variant="danger" className="bh-alert" data-testid="scorecard-error">{load.m} <button type="button" className="small" onClick={() => setRetry((n) => n + 1)}>Try again</button></div>
  const { score, passing, checks } = load.v
  return (
    <div className="stack" data-testid="scorecard">
      <p><strong data-testid="score">Score {score} / 100</strong> <span data-testid="passing"><span aria-hidden="true">{passing ? '✓ ' : '✗ '}</span>{passing ? 'Passing' : 'Not passing'}</span></p>
      {groupChecks(checks).map((g) => (
        <div key={g.id} data-testid="check-group" data-group={g.id}>
          <h3>{g.label}</h3>
          <ul style={{ listStyle: 'none', padding: 0 }} className="stack">
            {g.checks.map((c) => (
              <li key={c.id} data-testid="check" data-status={c.status}>
                <span data-testid="check-status"><span aria-hidden="true">{icon(c.status)}</span>{label(c.status)}</span> <code>{c.id}</code>
                {c.status !== 'pass' && <p data-testid="check-detail">{c.detail}</p>}
                <FixAction check={c} projectId={projectId} busy={busy} onOpenUpgrade={onOpenUpgrade} />
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}

function Detail({ projectId, id, onChanged }: { projectId: string; id: string; onChanged: () => void }) {
  const [load, setLoad] = useState<Load<UpgradeProposalDetail>>({ s: 'loading' })
  const [patch, setPatch] = useState<Load<string>>({ s: 'loading' })
  const [retry, setRetry] = useState(0)
  const [confirm, setConfirm] = useState<'dismiss' | 'applied' | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState('')
  useEffect(() => {
    let dead = false
    setLoad({ s: 'loading' }); setPatch({ s: 'loading' }); setConfirm(null); setError(''); setCopied('')
    api.getUpgrade(projectId, id).then((v) => { if (!dead) setLoad({ s: 'ok', v }) }, (e) => { if (!dead) setLoad({ s: 'error', m: upgradeError(e, 'Could not load the proposal') }) })
    api.getUpgradePatch(projectId, id).then((v) => { if (!dead) setPatch({ s: 'ok', v }) }, (e) => { if (!dead) setPatch({ s: 'error', m: upgradeError(e, 'Could not load the patch') }) })
    return () => { dead = true }
  }, [projectId, id, retry])

  async function decide(kind: 'dismiss' | 'applied') {
    setBusy(true); setError('')
    try {
      const v = await (kind === 'dismiss' ? api.dismissUpgrade(projectId, id) : api.markUpgradeApplied(projectId, id))
      setLoad({ s: 'ok', v }); setConfirm(null); onChanged()
    } catch (e) { setError(upgradeError(e)); setConfirm(null) } finally { setBusy(false) }
  }
  async function copy(text: string) {
    try { await navigator.clipboard.writeText(text); setCopied('Copied.') } catch { setCopied('Copying is not available here. Select the command and copy it by hand.') }
  }

  if (load.s === 'loading') return <p role="status" className="empty-state">Loading proposal…</p>
  if (load.s === 'error') return <div role="alert" data-variant="danger" className="bh-alert" data-testid="detail-error">{load.m} <button type="button" className="small" onClick={() => setRetry((n) => n + 1)}>Try again</button></div>
  const p = load.v
  const changes = readBlockChanges(p.block_changes)
  const files = readFiles(p.files)
  const migrations = readMigrations(p.migrations)
  const sbom = readSbom(p.sbom_diff)
  const sc = p.scorecard as { passing?: unknown }
  const sbomRows = [...sbom.added.map((e) => ({ k: 'Added', e })), ...sbom.removed.map((e) => ({ k: 'Removed', e })), ...sbom.changed.map((e) => ({ k: 'Changed', e }))]
  return (
    <div className="stack" data-testid="detail">
      <p data-testid="detail-status">Status: <strong>{p.status}</strong> · {p.from_generator_version ?? 'unknown'} to {p.to_generator_version} · {p.file_count} files</p>
      {error && <div role="alert" data-variant="danger" className="bh-alert" data-testid="decide-error">{error}</div>}

      <h3>Block versions</h3>
      {changes.length === 0 ? <p className="muted">No block versions change.</p> : (
        <ul data-testid="block-changes">{changes.map((c) => <li key={c.block}><code>{c.block}</code> {c.from ?? 'none'} to {c.to ?? 'none'} <span data-testid="bump" data-bump={c.bump}>{c.bump}</span></li>)}</ul>
      )}

      <h3>Files</h3>
      {files.length === 0 ? <p className="muted">No files change.</p> : (
        <table data-testid="files"><caption className="sr-only">Files changed by zone</caption><thead><tr><th scope="col">Path</th><th scope="col">Zone</th><th scope="col">Change</th></tr></thead>
          <tbody>{files.map((f) => <tr key={f.path} data-testid="file-row"><td><code>{f.path}</code></td><td>{f.zone}</td><td>{f.change}</td></tr>)}</tbody></table>
      )}
      {(p.kept ?? []).length > 0 && <p className="muted" data-testid="kept">Left untouched (yours): {(p.kept ?? []).join(', ')}</p>}

      <h3>Dependencies (SBOM diff)</h3>
      {sbomRows.length === 0 ? <p className="muted">No dependency changes.</p> : (
        <ul data-testid="sbom">{sbomRows.map(({ k, e }) => <li key={`${k}-${e.name}`}>{k}: <code>{e.name}</code> {k === 'Changed' ? `${e.from ?? ''} to ${e.to ?? ''}` : e.spec ?? ''}</li>)}</ul>
      )}

      <h3>Migrations</h3>
      {migrations.length === 0 ? <p className="muted">No migrations.</p> : <ul data-testid="migrations">{migrations.map((m) => <li key={m.path}><code>{m.path}</code> ({m.change})</li>)}</ul>}

      <h3>Auto-apply eligibility</h3>
      <p data-testid="eligibility"><span aria-hidden="true">{p.auto_apply_eligible ? '✓ ' : '– '}</span>{eligibilityReason(p.auto_apply_eligible, changes, files, migrations, typeof sc.passing === 'boolean' ? sc.passing : null)} <small className="muted">Nothing is applied for you; this is only a flag.</small></p>

      <h3>Patch</h3>
      {patch.s === 'loading' && <p role="status" className="empty-state">Loading patch…</p>}
      {patch.s === 'error' && <div role="alert" data-variant="danger" className="bh-alert" data-testid="patch-error">{patch.m}</div>}
      {patch.s === 'ok' && (
        <>
          <pre tabIndex={0} aria-label="Upgrade patch" data-testid="patch" style={{ maxHeight: '24rem', overflow: 'auto' }}>{patch.v}</pre>
          <p className="hstack">
            <button type="button" onClick={() => saveBlob(new Blob([patch.v], { type: 'text/x-diff' }), patchFilename(p.id))} data-testid="download-patch">Download patch</button>
            <code data-testid="apply-command">{applyCommand(p.id)}</code>
            <button type="button" className="outline" onClick={() => void copy(applyCommand(p.id))} aria-label="Copy command for git apply" data-testid="copy-command">Copy command</button>
          </p>
          <p role="status" aria-live="polite">{copied && <small data-testid="copied">{copied}</small>}</p>
        </>
      )}

      {p.status === 'open' && (
        <div className="hstack" data-testid="decide">
          {confirm === null && <>
            <button type="button" disabled={busy} onClick={() => setConfirm('applied')} data-testid="mark-applied">Mark applied</button>
            <button type="button" className="outline" disabled={busy} onClick={() => setConfirm('dismiss')} data-testid="dismiss">Dismiss</button>
          </>}
          {confirm !== null && <>
            <span>{confirm === 'dismiss' ? 'Dismiss this proposal? You can create a new one later.' : 'Mark this proposal as applied? Only do this after you applied the patch yourself.'}</span>
            <button type="button" disabled={busy} onClick={() => void decide(confirm)} data-testid="confirm-decide">{confirm === 'dismiss' ? 'Yes, dismiss' : 'Yes, mark applied'}</button>
            <button type="button" className="outline" onClick={() => setConfirm(null)}>Cancel</button>
          </>}
        </div>
      )}
      {p.status !== 'open' && <p className="muted" data-testid="closed-note">This proposal is {p.status}{p.decided_at ? ` (${shortDate(p.decided_at)})` : ''}.</p>}
    </div>
  )
}

function UpgradesBody({ projectId }: { projectId: string }) {
  const [list, setList] = useState<Load<UpgradeProposalSummary[]>>({ s: 'loading' })
  const [retry, setRetry] = useState(0)
  const [sel, setSel] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [bump, setBump] = useState(0)
  const live = useRef(true)
  useEffect(() => { live.current = true; return () => { live.current = false } }, [])

  useEffect(() => {
    let dead = false
    setList({ s: 'loading' })
    api.listUpgrades(projectId).then((r) => { if (!dead) setList({ s: 'ok', v: r.items }) }, (e) => { if (!dead) setList({ s: 'error', m: upgradeError(e, 'Could not load the proposals') }) })
    return () => { dead = true }
  }, [projectId, retry])

  const create = useCallback(async () => {
    setBusy(true); setError('')
    try {
      const d = await api.createUpgrade(projectId)
      if (!live.current) return
      setSel(d.id); setRetry((n) => n + 1); setBump((n) => n + 1)
    } catch (e) { if (live.current) setError(upgradeError(e)) } finally { if (live.current) setBusy(false) }
  }, [projectId])

  return (
    <div className="stack">
      {error && <div role="alert" data-variant="danger" className="bh-alert" data-testid="create-error">{error}</div>}
      <h2>Scorecard</h2>
      <ScorecardSection projectId={projectId} busy={busy} onOpenUpgrade={() => void create()} refresh={bump} />
      <h2>Upgrade proposals</h2>
      <p><button type="button" disabled={busy} onClick={() => void create()} data-testid="create-proposal">{busy ? 'Working…' : 'Check for an upgrade'}</button></p>
      {list.s === 'loading' && <p role="status" className="empty-state">Loading proposals…</p>}
      {list.s === 'error' && <div role="alert" data-variant="danger" className="bh-alert" data-testid="list-error">{list.m} <button type="button" className="small" onClick={() => setRetry((n) => n + 1)}>Try again</button></div>}
      {list.s === 'ok' && list.v.length === 0 && <p className="empty-state" data-testid="list-empty">No upgrade proposals yet.</p>}
      {list.s === 'ok' && list.v.length > 0 && (
        <ul className="stack" style={{ listStyle: 'none', padding: 0 }} data-testid="proposals">
          {list.v.map((p) => (
            <li key={p.id} data-testid="proposal" data-status={p.status}>
              <button type="button" className="outline" aria-pressed={sel === p.id} onClick={() => setSel(p.id)} aria-label={`Open proposal ${p.from_generator_version ?? 'unknown'} to ${p.to_generator_version}, ${p.status}`}>
                {p.from_generator_version ?? 'unknown'} to {p.to_generator_version}
              </button>{' '}
              <span data-testid="proposal-status">{p.status}</span> · {p.file_count} files · {shortDate(p.created_at)}
            </li>
          ))}
        </ul>
      )}
      {sel && (<><h2>Proposal detail</h2><Detail key={sel} projectId={projectId} id={sel} onChanged={() => { setRetry((n) => n + 1); setBump((n) => n + 1) }} /></>)}
    </div>
  )
}

/** Ship > Upgrades: generator-upgrade proposals and the project scorecard (builder routes, not the generated project). */
export function UpgradesPage({ projectId }: { projectId: string }) {
  return (
    <section aria-labelledby="upgrades-h" data-testid="upgrades-page" className="stack">
      <h1 id="upgrades-h">Upgrades</h1>
      <p className="muted">See how healthy the generated project is, and when a newer generator would change it. A proposal is a patch you apply yourself; your own code is never touched.</p>
      <UpgradesBody key={projectId} projectId={projectId} />
    </section>
  )
}
