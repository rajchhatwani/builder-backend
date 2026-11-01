import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../../api/client'
import type { StateMachineBody, TransitionBody, ValidationIssue } from '../../api/types'

// React Flow + dagre load only when this page is opened (own chunk, not in the main bundle).
// (layout.ts imports dagre: only MachineDiagram may import it, or dagre lands in the main bundle)
const MachineDiagram = lazy(() => import('./MachineDiagram'))

type Load =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; machines: StateMachineBody[]; issues: ValidationIssue[] }

export function TransitionDetail({ t }: { t: TransitionBody }) {
  const from = t.from_states ?? []
  const roles = t.roles ?? []
  return (
    <div className="card machine-detail" data-testid="transition-detail" aria-live="polite">
      <h2>{t.name}</h2>
      <dl>
        <dt>Moves</dt>
        <dd>
          {from.join(', ') || '(no source state)'} → {t.to_state}
        </dd>
        <dt>Guard</dt>
        <dd>{t.when ? <code>{t.when}</code> : <span className="muted">None: always allowed in these states</span>}</dd>
        <dt>Roles</dt>
        <dd>{roles.length ? roles.join(', ') : <span className="muted">Any role with access to the record</span>}</dd>
        <dt>Runs</dt>
        <dd>{t.auto ? 'Automatically after a save, when the guard is true' : 'Manually, when a user triggers it'}</dd>
      </dl>
    </div>
  )
}

export function MachinesPage({ projectId }: { projectId: string }) {
  const [load, setLoad] = useState<Load>({ status: 'loading' })
  const [entity, setEntity] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoad({ status: 'loading' })
    Promise.all([api.getStateMachines(projectId), api.getBehaviorIssues(projectId)])
      .then(([machines, issues]) => {
        if (cancelled) return
        setLoad({ status: 'ready', machines: machines.state_machines, issues: issues.issues })
        setEntity((cur) => cur ?? machines.state_machines[0]?.entity ?? null)
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoad({ status: 'error', message: err instanceof Error ? err.message : 'Could not load state machines' })
      })
    return () => {
      cancelled = true
    }
  }, [projectId, attempt])

  const machine = useMemo(
    () => (load.status === 'ready' ? load.machines.find((m) => m.entity === entity) ?? load.machines[0] : undefined),
    [load, entity],
  )
  const onSelect = useCallback((name: string) => setSelected(name), [])
  const transition = machine && selected ? (machine.transitions ?? []).find((t) => t.name === selected) : undefined

  return (
    <>
      <div className="page-header">
        <div>
          <h1>State machines</h1>
          <p>How a record moves through its states: who may move it, under which condition, and what happens by itself.</p>
        </div>
      </div>

      {load.status === 'loading' && <p className="empty-state">Loading state machines…</p>}

      {load.status === 'error' && (
        <div className="card empty-hero" role="alert">
          <h2>We could not load the state machines</h2>
          <p>{load.message}</p>
          <button onClick={() => setAttempt((a) => a + 1)}>Try again</button>
        </div>
      )}

      {load.status === 'ready' && load.machines.length === 0 && (
        <div className="card empty-hero" data-testid="machines-empty">
          <h2>No state machines yet</h2>
          <p>
            A state machine gives a record, such as an invoice or a leave request, a set of states and the allowed moves
            between them. Import a spec that declares <code>state_machines</code> to see them here.
          </p>
        </div>
      )}

      {load.status === 'ready' && machine && (
        <>
          {load.issues.length > 0 && (
            <div className="card" style={{ marginBlockEnd: 'var(--space-4)' }}>
              <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-3)' }}>
                {load.issues.length} {load.issues.length === 1 ? 'problem' : 'problems'} in the behaviour sections.
              </div>
              <ul className="issue-list">
                {load.issues.map((i, n) => (
                  <li key={n}>
                    <span>
                      {i.message}
                      <small className="muted"> · {i.path}</small>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="machines-grid">
            <nav aria-label="State machines" className="card machines-list">
              <ul>
                {load.machines.map((m) => (
                  <li key={m.entity}>
                    <button
                      className={m.entity === machine.entity ? '' : 'outline'}
                      aria-pressed={m.entity === machine.entity}
                      onClick={() => {
                        setEntity(m.entity)
                        setSelected(null)
                      }}
                    >
                      <strong>{m.entity}</strong>
                      <small>
                        {m.field} · {(m.transitions ?? []).length} transitions
                      </small>
                    </button>
                  </li>
                ))}
              </ul>
            </nav>

            <section aria-label={`${machine.entity} diagram`} className="card machine-stage">
              <Suspense fallback={<p className="empty-state">Loading diagram…</p>}>
                <MachineDiagram machine={machine} selected={selected} onSelect={onSelect} />
              </Suspense>
            </section>

            <aside aria-label="Transitions" className="machine-side">
              {transition ? (
                <TransitionDetail t={transition} />
              ) : (
                <div className="card machine-detail" data-testid="transition-detail-empty">
                  <p className="muted">Select a transition in the diagram or the list to see its guard, roles and trigger.</p>
                </div>
              )}
              <ul className="machine-transitions" aria-label={`${machine.entity} transitions`}>
                {(machine.transitions ?? []).map((t) => (
                  <li key={t.name}>
                    <button className="ghost small" aria-pressed={selected === t.name} onClick={() => setSelected(t.name)}>
                      {t.name}
                      <small className="muted">
                        {' '}
                        {(t.from_states ?? []).join(', ')} → {t.to_state}
                      </small>
                    </button>
                  </li>
                ))}
              </ul>
            </aside>
          </div>
        </>
      )}
    </>
  )
}
