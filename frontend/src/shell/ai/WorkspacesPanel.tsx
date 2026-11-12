import { useCallback, useEffect, useId, useState } from 'react'
import { api } from '../../api/client'
import type { WorkspaceInfo } from '../../api/types'
import { ConfirmPrompt } from '../../components/ConfirmPrompt'
import { errMsg } from './useRunParam'

type Pending = { kind: 'rollback'; ws: WorkspaceInfo; checkpointId: string; label: string } | { kind: 'discard'; ws: WorkspaceInfo }

/** Draft workspaces: list, create, checkpoint, roll back to a checkpoint (confirmed) and discard (confirmed). */
export function WorkspacesPanel({ projectId }: { projectId: string }) {
  const [items, setItems] = useState<WorkspaceInfo[] | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [name, setName] = useState('')
  const [labels, setLabels] = useState<Record<string, string>>({})
  const [pending, setPending] = useState<Pending | null>(null)
  const nameId = useId()

  const load = useCallback(async () => {
    try { setItems(await api.listWorkspaces(projectId)); setError('') } catch (e) { setError(errMsg(e)); setItems((cur) => cur ?? []) }
  }, [projectId])
  useEffect(() => { void load() }, [load])

  const run = async (fn: () => Promise<unknown>): Promise<boolean> => {
    setBusy(true); setError('')
    try { await fn(); await load(); return true } catch (e) { setError(errMsg(e)); return false } finally { setBusy(false) }
  }
  const create = async () => { if (await run(() => api.createWorkspace(projectId, name.trim() || 'draft'))) setName('') }
  const checkpoint = (ws: WorkspaceInfo) => run(() => api.createCheckpoint(projectId, ws.id, (labels[ws.id] ?? '').trim() || 'checkpoint'))
  const confirm = async () => {
    if (!pending) return
    const p = pending
    const ok = await run(() => p.kind === 'rollback' ? api.rollbackWorkspace(projectId, p.ws.id, p.checkpointId) : api.discardWorkspace(projectId, p.ws.id))
    if (ok) setPending(null)
  }

  return (
    <section className="card" aria-labelledby="ws-h" data-testid="workspaces">
      <h2 id="ws-h">Draft workspaces</h2>
      <p className="muted small-text">A workspace is a private draft of your project. Save a checkpoint before risky work, and roll back to it if needed.</p>
      {error && <p className="bh-error" role="alert" data-testid="ws-error">{error}</p>}
      <div className="hstack">
        <label htmlFor={nameId}>New workspace name</label>
        <input id={nameId} value={name} maxLength={100} placeholder="draft" onChange={(e) => setName(e.target.value)} data-testid="ws-name" />
        <button disabled={busy} onClick={() => void create()} data-testid="ws-create">Create workspace</button>
      </div>
      {items === null && <p className="empty-state">Loading…</p>}
      {items && items.length === 0 && <p className="empty-state" data-testid="ws-empty">No workspaces yet.</p>}
      {items && items.length > 0 && (
        <ul aria-label="Workspaces" data-testid="ws-list">
          {items.map((ws) => (
            <li key={ws.id} data-testid="ws-item" data-ws={ws.id}>
              <strong>{ws.name}</strong> <span className="badge badge-muted" data-testid="ws-state">{ws.state}</span>{' '}
              <small className="muted">branch {ws.branch}, spec #{ws.spec_seq}</small>
              {ws.cleanup_incomplete && <small className="ai-bad" data-testid="ws-cleanup"> Cleanup incomplete: discard again to retry.</small>}
              <div className="hstack">
                <label htmlFor={`${nameId}-${ws.id}`}>Checkpoint label for {ws.name}</label>
                <input id={`${nameId}-${ws.id}`} value={labels[ws.id] ?? ''} maxLength={100} placeholder="checkpoint" onChange={(e) => setLabels((l) => ({ ...l, [ws.id]: e.target.value }))} data-testid="ws-label" />
                <button className="outline" disabled={busy} onClick={() => void checkpoint(ws)} data-testid="ws-checkpoint" aria-label={`Save a checkpoint of ${ws.name}`}>Save checkpoint</button>
                <button className="outline" disabled={busy} onClick={() => setPending({ kind: 'discard', ws })} data-testid="ws-discard" aria-label={`Discard ${ws.name}`}>Discard</button>
              </div>
              {ws.checkpoints.length > 0 && (
                <ul aria-label={`Checkpoints of ${ws.name}`}>
                  {ws.checkpoints.map((c) => (
                    <li key={c.id} data-testid="ws-checkpoint-item">
                      {c.label} <small className="muted">spec #{c.spec_seq}, {c.created_at.slice(0, 16).replace('T', ' ')}</small>{' '}
                      <button className="outline small" disabled={busy} onClick={() => setPending({ kind: 'rollback', ws, checkpointId: c.id, label: c.label })} data-testid="ws-rollback" aria-label={`Roll ${ws.name} back to ${c.label}`}>Roll back</button>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
      {pending && (
        <ConfirmPrompt
          testId="ws-confirm"
          title={pending.kind === 'rollback' ? `Roll back ${pending.ws.name} to "${pending.label}"?` : `Discard ${pending.ws.name}?`}
          confirmLabel={pending.kind === 'rollback' ? 'Roll back' : 'Discard workspace'}
          busy={busy}
          onConfirm={() => void confirm()}
          onCancel={() => setPending(null)}
        >
          {pending.kind === 'rollback'
            ? 'Everything changed in this workspace since that checkpoint is lost.'
            : 'The draft and its checkpoints are removed. This cannot be undone.'}
        </ConfirmPrompt>
      )}
    </section>
  )
}
