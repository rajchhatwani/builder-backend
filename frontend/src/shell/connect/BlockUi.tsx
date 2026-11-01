import type { ReactNode } from 'react'
import type { ValidationIssue } from '../../api/types'
import type { SpecLoad } from './useSpecBlocks'

export function PageHeader({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        <p>{children}</p>
      </div>
    </div>
  )
}

/** Honest label for pages whose section has no builder endpoint yet. */
export function ReadOnlyNotice({ what }: { what: string }) {
  return (
    <div className="card co-note" data-testid="readonly-notice" role="note">
      <strong>Read-only for now.</strong> {what} has no builder endpoint yet, so this page shows what the project spec declares.
      Change it in the spec (Workbench, import, or the agent); this page updates on reload.
    </div>
  )
}

export function Issues({ issues }: { issues: ValidationIssue[] }) {
  if (!issues.length) return null
  return (
    <div role="alert" data-variant="danger" className="bh-alert" data-testid="block-issues">
      The backend validator found {issues.length} {issues.length === 1 ? 'problem' : 'problems'} in this part of the spec.
      <ul>
        {issues.map((i, k) => (
          <li key={k}>
            <code>{i.path}</code> {i.message}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function Off({ what, children }: { what: string; children?: ReactNode }) {
  return (
    <div className="card empty-hero" data-testid="block-off">
      <h2>{what} is not switched on</h2>
      <p>{children ?? 'The spec has no enabled block for it, so nothing is generated.'}</p>
    </div>
  )
}

/** Loading / error wrapper shared by the spec-reading pages. */
export function SpecGate({ title, intro, load, retry, children }: {
  title: string
  intro: string
  load: SpecLoad
  retry: () => void
  children: (l: Extract<SpecLoad, { status: 'ready' }>) => ReactNode
}) {
  return (
    <div className="co-page">
      <PageHeader title={title}>{intro}</PageHeader>
      {load.status === 'loading' && <p className="empty-state" role="status">Loading…</p>}
      {load.status === 'error' && (
        <div role="alert" data-variant="danger" className="bh-alert" data-testid="block-error">
          Could not load the spec: {load.message} <button className="small" onClick={retry}>Try again</button>
        </div>
      )}
      {load.status === 'ready' && children(load)}
    </div>
  )
}

export function Kv({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="co-kv">
      {items.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  )
}

export const Status = ({ on }: { on: boolean | undefined }) => (
  <span className={on ? 'badge' : 'badge badge-muted'}>{on ? 'On' : 'Off'}</span>
)

/** A table that scrolls sideways inside its own focusable region (keyboard users can scroll it; axe: scrollable-region-focusable). */
export function Scroll({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="co-scroll" role="region" aria-label={label} tabIndex={0}>
      {children}
    </div>
  )
}
