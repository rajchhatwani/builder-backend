import type { ReactNode } from 'react'
import { countIssues, type SectionIssues } from './formLogic'

/** Label + control + the backend's (or client) messages for that field, linked for screen readers. */
export function Field({ id, label, messages, hint, children }: {
  id: string
  label: string
  messages?: string[]
  hint?: string
  children: (p: { id: string; 'aria-invalid'?: true; 'aria-describedby'?: string }) => ReactNode
}) {
  const bad = !!messages?.length
  const errId = `${id}-err`
  return (
    <div className="bh-field" data-invalid={bad || undefined}>
      <label htmlFor={id}>{label}</label>
      {children({ id, ...(bad ? { 'aria-invalid': true as const, 'aria-describedby': errId } : {}) })}
      {hint && !bad && <small className="muted">{hint}</small>}
      {bad && (
        <small id={errId} className="bh-error" data-testid="field-error">
          {messages!.join(' ')}
        </small>
      )}
    </div>
  )
}

export function SaveBar({ dirty, saving, onSave, onDiscard, note, error }: {
  dirty: boolean
  saving: boolean
  onSave: () => void
  onDiscard: () => void
  note: string
  error: string
}) {
  return (
    <div className="bh-savebar">
      <button onClick={onSave} disabled={!dirty || saving}>{saving ? 'Saving…' : 'Save'}</button>
      <button className="outline" onClick={onDiscard} disabled={!dirty || saving}>Discard changes</button>
      {dirty && !saving && <small className="muted">Unsaved changes</small>}
      <span role="status" aria-live="polite">{note && <small data-testid="save-note">{note}</small>}</span>
      {error && <div role="alert" data-variant="danger" className="bh-alert">{error}</div>}
    </div>
  )
}

export function ConflictBanner({ onReload }: { onReload: () => void }) {
  return (
    <div role="alert" data-variant="warning" className="bh-conflict" data-testid="conflict">
      Someone else changed this section since you opened it, so your save was not applied. Reload to see their version
      (your unsaved edits will be lost). <button className="small" onClick={onReload}>Reload</button>
    </div>
  )
}

export function IssueSummary({ issues }: { issues: SectionIssues }) {
  const n = countIssues(issues)
  if (!n) return null
  return (
    <div role="alert" data-variant="danger" className="bh-alert" data-testid="issue-summary">
      The backend validator found {n} {n === 1 ? 'problem' : 'problems'}. They are shown next to the fields below.
      {issues.section.length > 0 && (
        <ul>
          {issues.section.map((m, i) => (
            <li key={i}>{m}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function LoadFailed({ what, message, onRetry }: { what: string; message: string; onRetry: () => void }) {
  return (
    <div className="card empty-hero" role="alert">
      <h2>We could not load {what}</h2>
      <p>{message}</p>
      <button onClick={onRetry}>Try again</button>
    </div>
  )
}
