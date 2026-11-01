import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api/client'
import type { SpecOp } from '../../api/types'
import { useUi } from '../../components/Ui'
import { actorLabel, canRestore, failureMessage, formatWhen, impactText, latestSeq, opSummary, opsToUndo } from './timelineLogic'

const PAGE = 200
const MAX_PAGES = 5 // 1000 operations; older ones are reported as not loaded

type Load =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; ops: SpecOp[]; total: number }

async function loadAll(projectId: string): Promise<{ ops: SpecOp[]; total: number }> {
  const ops: SpecOp[] = []
  let total = 0
  for (let i = 0; i < MAX_PAGES; i++) {
    const page = await api.listSpecOps(projectId, PAGE, i * PAGE)
    total = page.total
    ops.push(...page.items)
    if (ops.length >= total || page.items.length === 0) break
  }
  return { ops, total }
}

/** Build > History timeline: the spec op-log (who changed what, when) with undo, redo and restore to a version. */
export function TimelinePage({ projectId }: { projectId: string }) {
  const { confirm, toast } = useUi()
  const [load, setLoad] = useState<Load>({ status: 'loading' })
  const [selected, setSelected] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [alert, setAlert] = useState<string | null>(null)
  const statusRef = useRef<HTMLDivElement>(null)

  const reload = useCallback(async () => {
    try {
      const r = await loadAll(projectId)
      setLoad({ status: 'ready', ...r })
      return r
    } catch (err) {
      setLoad({ status: 'error', message: err instanceof Error ? err.message : 'Could not load the history' })
      return null
    }
  }, [projectId])

  useEffect(() => {
    setLoad({ status: 'loading' })
    setSelected(null)
    void reload()
  }, [reload])

  const header = (
    <div className="page-header">
      <div>
        <h1>History timeline</h1>
        <p>Every change to the project spec, who made it and when. Pick a version to see what restoring it would take back.</p>
      </div>
    </div>
  )

  if (load.status === 'loading') return <>{header}<p className="empty-state" role="status">Loading the history…</p></>
  if (load.status === 'error') {
    return (
      <>
        {header}
        <div role="alert" data-variant="danger" className="bh-alert" data-testid="timeline-error">
          Could not load the history: {load.message}{' '}
          <button className="small" onClick={() => { setLoad({ status: 'loading' }); void reload() }}>Try again</button>
        </div>
      </>
    )
  }

  const { ops, total } = load
  const latest = latestSeq(ops)
  const undone = selected === null ? [] : opsToUndo(ops, selected)
  const target = selected === null ? null : ops.find((o) => o.seq === selected) ?? null

  async function run(fn: () => Promise<unknown>, done: string) {
    setBusy(true)
    setAlert(null)
    try {
      await fn()
      setSelected(null)
      await reload()
      toast(done)
      statusRef.current?.focus()
    } catch (err) {
      const f = failureMessage(err)
      if (f.conflict) {
        setSelected(null)
        await reload()
      }
      setAlert(f.text)
      statusRef.current?.focus()
    } finally {
      setBusy(false)
    }
  }

  async function restore() {
    if (selected === null) return
    const label = selected === 0 ? 'the start (before the first change)' : `version ${selected}`
    const ok = await confirm({
      title: `Restore the draft spec to ${label}?`,
      message: `This takes back ${impactText(undone)}. The restore is recorded as a new entry, so you can undo it. Generated projects already downloaded are not changed.`,
      confirmLabel: 'Restore',
      danger: true,
    })
    if (ok) await run(() => api.restoreSpec(projectId, selected), `Restored to ${label}.`)
  }

  return (
    <>
      {header}
      <div ref={statusRef} tabIndex={-1} role="group" className="bh-actions" aria-label="History actions">
        <button className="outline small" disabled={busy || ops.length === 0} onClick={() => run(() => api.undoSpec(projectId), 'Undid the last change.')}>Undo last change</button>
        <button className="outline small" disabled={busy || ops.length === 0} onClick={() => run(() => api.redoSpec(projectId), 'Redid the change.')}>Redo</button>
        <small className="muted" role="status">{total === 0 ? 'No changes recorded' : `${total} ${total === 1 ? 'change' : 'changes'} recorded, newest first`}</small>
      </div>
      {alert && <div role="alert" data-variant="warning" className="bh-conflict" data-testid="timeline-alert">{alert}</div>}

      {ops.length === 0 ? (
        <p className="empty-state" data-testid="timeline-empty">
          No changes recorded yet. Edit the data model or a behaviour page and the change appears here.
        </p>
      ) : (
        <div className="bh-grid">
          <section aria-labelledby="tl-list">
            <h2 id="tl-list">Versions</h2>
            <ol className="bh-timeline" data-testid="timeline-list">
              {ops.map((o) => (
                <li key={o.seq}>
                  <button
                    className={selected === o.seq ? '' : 'outline'}
                    aria-pressed={selected === o.seq}
                    onClick={() => setSelected(o.seq)}
                  >
                    <strong>Version {o.seq}: {opSummary(o)}</strong>
                    <small className="muted"> {actorLabel(o)} · <time dateTime={o.created_at}>{formatWhen(o.created_at)}</time>{o.seq === latest ? ' · current' : ''}</small>
                  </button>
                </li>
              ))}
              {ops.length >= total && (
                <li>
                  <button className={selected === 0 ? '' : 'outline'} aria-pressed={selected === 0} onClick={() => setSelected(0)}>
                    <strong>Start</strong> <small className="muted">before the first change</small>
                  </button>
                </li>
              )}
            </ol>
            {ops.length < total && <p className="muted small-text" data-testid="timeline-truncated">Showing the newest {ops.length} of {total} changes.</p>}
          </section>

          <section aria-labelledby="tl-detail" aria-live="polite">
            <h2 id="tl-detail">Restore preview</h2>
            {selected === null ? (
              <p className="muted">Select a version to see what restoring it would do.</p>
            ) : (
              <div data-testid="timeline-preview">
                <p>
                  <strong>{selected === 0 ? 'Start' : `Version ${selected}`}</strong>
                  {target ? `: ${opSummary(target)}` : ''}
                </p>
                <p data-testid="timeline-impact">Restoring takes back {impactText(undone)}</p>
                {undone.length > 0 && (
                  <ul>
                    {undone.slice(0, 20).map((o) => <li key={o.seq}>Version {o.seq}: {opSummary(o)}</li>)}
                    {undone.length > 20 && <li>and {undone.length - 20} more</li>}
                  </ul>
                )}
                <button disabled={busy || !canRestore(ops, selected)} onClick={restore}>
                  {canRestore(ops, selected) ? 'Restore the draft to this version…' : 'Already at this version'}
                </button>
              </div>
            )}
          </section>
        </div>
      )}
    </>
  )
}
