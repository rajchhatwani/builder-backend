import type { ComponentPropsWithRef, CSSProperties } from 'react'

type Space = 0 | 1 | 2 | 3 | 4 | 5 | 6 | 8 | 10 | 12
type LayoutProps = ComponentPropsWithRef<'div'> & { gap?: Space }

function Layout({ kind, gap = 3, className = '', style, ...props }: LayoutProps & { kind: 'stack' | 'row' | 'grid' }) {
  return <div {...props} className={`v2-${kind} ${className}`} style={{ ...style, '--gap': `var(--s${gap})` } as CSSProperties} />
}

export function Stack(props: LayoutProps) { return <Layout kind="stack" {...props} /> }
export function Row(props: LayoutProps) { return <Layout kind="row" {...props} /> }
export function Grid(props: LayoutProps) { return <Layout kind="grid" {...props} /> }
