import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'
import { useT } from '../i18n'
import { Button } from './controls'
import { Card } from './surface'
import { Row, Stack } from './layout'

export type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger'

export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: Tone }) {
  return <span className="v2-badge" data-tone={tone}>{children}</span>
}

export function Chip({ children }: { children: ReactNode }) {
  return <span className="v2-chip">{children}</span>
}

export function Alert({ children, tone = 'info', action }: { children: ReactNode; tone?: Tone; action?: ReactNode }) {
  return <Row className="v2-alert" data-tone={tone} role={tone === 'danger' ? 'alert' : 'status'}><div>{children}</div>{action}</Row>
}

export function Skeleton({ label, lines = 3 }: { label?: string; lines?: number }) {
  const t = useT()
  return (
    <Stack role="status" aria-label={label ?? t('common.loading')} className="v2-skeleton">
      {Array.from({ length: lines }, (_, index) => <span key={index} aria-hidden />)}
    </Stack>
  )
}

export function Spinner({ label }: { label?: string }) {
  const t = useT()
  return <span className="v2-spinner" role="status" aria-label={label ?? t('common.loading')} />
}

export function EmptyState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <Card className="v2-empty">
      <Stack gap={2}>
        <h2>{title}</h2>
        {description && <p className="v2-muted">{description}</p>}
        {action && <Row>{action}</Row>}
      </Stack>
    </Card>
  )
}

export function DesktopOnlyCard({ action }: { action?: ReactNode }) {
  const t = useT()
  return <EmptyState title={t('common.desktopOnly')} action={action} />
}

type BoundaryProps = { children: ReactNode; fallback: (retry: () => void) => ReactNode; onError?: (error: Error, info: ErrorInfo) => void }
class Boundary extends Component<BoundaryProps, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch(error: Error, info: ErrorInfo) { this.props.onError?.(error, info) }

  render() {
    return this.state.failed ? this.props.fallback(() => this.setState({ failed: false })) : this.props.children
  }
}

export function ErrorBoundary({ children, fallback, onError }: {
  children: ReactNode
  fallback?: BoundaryProps['fallback']
  onError?: BoundaryProps['onError']
}) {
  const t = useT()
  return <Boundary onError={onError} fallback={fallback ?? ((retry) => (
    <Alert tone="danger" action={<Button onClick={retry}>{t('common.retry')}</Button>}>{t('common.crash')}</Alert>
  ))}>{children}</Boundary>
}
