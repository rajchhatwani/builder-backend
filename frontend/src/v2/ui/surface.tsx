import type { ReactNode, ComponentPropsWithRef } from 'react'

export function Card({ className = '', ...props }: ComponentPropsWithRef<'section'>) {
  return <section className={`v2-card ${className}`} {...props} />
}

export function CodeBlock({ code, label }: { code: string; label?: string }) {
  return <pre className="v2-code" aria-label={label}><code>{code}</code></pre>
}

export function Progress({ label, value, max }: { label: string; value: number; max: number }) {
  return <progress className="v2-progress" aria-label={label} value={Math.min(value, max)} max={max} />
}

export function Disclosure({ label, children, ...props }: ComponentPropsWithRef<'details'> & { label: ReactNode }) {
  return <details {...props} className="v2-disclosure"><summary>{label}</summary>{children}</details>
}
