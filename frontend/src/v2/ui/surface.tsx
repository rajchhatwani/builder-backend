import type { ReactNode, ComponentPropsWithRef } from 'react'

export function Card({ className = '', ...props }: ComponentPropsWithRef<'section'>) {
  return <section className={`v2-card ${className}`} {...props} />
}

export function CodeBlock({ code, label }: { code: string; label?: string }) {
  return <pre className="v2-code" aria-label={label}><code>{code}</code></pre>
}

export function Progress({ label, value, max, ...props }: { label: string; value: number; max: number; 'data-testid'?: string }) {
  return <progress {...props} className="v2-progress" aria-label={label} value={Math.min(value, max)} max={max} />
}

export function Disclosure({ label, children, ...props }: ComponentPropsWithRef<'details'> & { label: ReactNode }) {
  return <details {...props} className="v2-disclosure"><summary>{label}</summary>{children}</details>
}

export function RangeTrack({ offset, width, variant = 'default' }: { offset: number; width: number; variant?: 'default' | 'active' | 'warning' }) {
  const percent = (value: number) => (Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0) + '%'
  return <div className="v2-range-track" aria-hidden>
    <span data-variant={variant} style={{ insetInlineStart: percent(offset), inlineSize: percent(Math.min(width, 100 - offset)) }} />
  </div>
}
