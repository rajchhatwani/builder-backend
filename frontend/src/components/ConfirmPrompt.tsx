import { useId, type ReactNode } from 'react'

/** An inline confirmation step for an action that cannot be undone. Renders as an alert dialog region (no native <dialog>, so it works in every test environment). */
export function ConfirmPrompt({ title, children, confirmLabel, busy = false, onConfirm, onCancel, testId = 'confirm-prompt' }: {
  title: string
  children?: ReactNode
  confirmLabel: string
  busy?: boolean
  onConfirm: () => void
  onCancel: () => void
  testId?: string
}) {
  const id = useId()
  return (
    <div role="alertdialog" aria-labelledby={`${id}-t`} aria-describedby={`${id}-d`} data-testid={testId} data-variant="danger" className="card">
      <h3 id={`${id}-t`}>{title}</h3>
      <div id={`${id}-d`}>{children}</div>
      <div className="row">
        <button type="button" onClick={onConfirm} disabled={busy} data-testid={`${testId}-confirm`}>{busy ? 'Working…' : confirmLabel}</button>
        <button type="button" className="outline" onClick={onCancel} disabled={busy} data-testid={`${testId}-cancel`}>Cancel</button>
      </div>
    </div>
  )
}
