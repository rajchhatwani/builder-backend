import type { ComponentPropsWithoutRef } from 'react'

export function Card({ className = '', ...props }: ComponentPropsWithoutRef<'section'>) {
  return <section className={`v2-card ${className}`} {...props} />
}

export function CodeBlock({ code, label }: { code: string; label?: string }) {
  return <pre className="v2-code" aria-label={label}><code>{code}</code></pre>
}
