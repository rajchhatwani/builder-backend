import { lazy, Suspense } from 'react'
import type { ComponentType } from 'react'
import { useT } from '../i18n'
import { Alert, Button, Card, ErrorBoundary, Skeleton } from '../ui'

export function ScreenSkeleton({ label, headingKey }: { label?: string; headingKey?: string }) {
  const t = useT()
  return <Card className="v2-screen-placeholder">
    {headingKey && <h1 className="v2-visually-hidden">{t(headingKey)}</h1>}
    <Skeleton lines={8} label={label} />
  </Card>
}

export function LazyError() {
  const t = useT()
  return <Alert tone="danger" action={<Button onClick={() => location.reload()}>{t('common.reload')}</Button>}>{t('common.crash')}</Alert>
}

export function lazyScreen<Props extends object = Record<string, never>>(
  load: () => Promise<{ default: ComponentType<Props> }>,
  pendingHeadingKey?: string,
) {
  const Screen = lazy(load)
  return {
    preload: () => load().catch(() => undefined),
    Component: function LazyScreen(props: Props) {
      return <ErrorBoundary fallback={() => <LazyError />}>
        <Suspense fallback={<ScreenSkeleton headingKey={pendingHeadingKey} />}><Screen {...props} /></Suspense>
      </ErrorBoundary>
    },
  }
}
