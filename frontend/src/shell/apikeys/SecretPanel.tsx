import { useEffect, useRef, useState } from 'react'

export interface Secret { label: string; value: string }

/** Shows secrets exactly once. They live only in the props of this panel (component state of the page): no storage, no URL, no logging.
 *  Dismissing (or leaving the page / switching project) drops them. */
export function SecretPanel({ title, note, secrets, onDismiss }: { title: string; note: string; secrets: Secret[]; onDismiss: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const [copied, setCopied] = useState('')
  useEffect(() => { ref.current?.focus() }, [])

  async function copy(s: Secret) {
    try {
      await navigator.clipboard.writeText(s.value)
      setCopied(`${s.label} copied.`)
    } catch { setCopied(`Could not copy the ${s.label.toLowerCase()}: select it and copy by hand.`) }
  }

  return (
    <div ref={ref} tabIndex={-1} role="region" aria-label={title} className="bh-alert" data-variant="warning" data-testid="secret-panel">
      <p><strong>{title}</strong></p>
      <p>{note}</p>
      {secrets.map((s) => (
        <p key={s.label} className="hstack">
          <span>{s.label}:</span> <code data-testid="secret-value" style={{ wordBreak: 'break-all' }}>{s.value}</code>
          <button type="button" className="outline small" onClick={() => void copy(s)} aria-label={`Copy the ${s.label.toLowerCase()}`}>Copy</button>
        </p>
      ))}
      <p role="status" aria-live="polite">{copied && <small data-testid="secret-copied">{copied}</small>}</p>
      <button type="button" onClick={onDismiss} data-testid="secret-dismiss">I have saved it, dismiss</button>
    </div>
  )
}
