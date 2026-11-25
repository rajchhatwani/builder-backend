import type { ReactNode } from 'react'
import { Link } from '@tanstack/react-router'
import { useT } from '../../../i18n'
import { ConflictBanner, ReadOnlyNote } from '../../../patterns'
import { Alert, Button, Card, Skeleton, Stack } from '../../../ui'
import { entryError } from '../api/entry'
import './entry.css'

export function EntryFrame({ title, children, testId }: { title: string; children: ReactNode; testId?: string }) {
  return <Stack className="v2-entry-frame" gap={4} data-testid={testId}>
    <h1>{title}</h1>
    {children}
  </Stack>
}

export function EntryCard({ title, children }: { title?: string; children: ReactNode }) {
  return <Card><Stack>{title && <h2>{title}</h2>}{children}</Stack></Card>
}

export function EntryLoading({ label, lines = 4 }: { label?: string; lines?: number }) {
  return <EntryCard><Skeleton lines={lines} label={label} /></EntryCard>
}

export function BackToSignIn({ label, next }: { label?: string; next?: string }) {
  const t = useT()
  return <Button asChild><Link to="/sign-in" search={{ next }}>{label ?? t('entry.backSignIn')}</Link></Button>
}

export function EntryProblem({ error, message, retry, retryLabel }: {
  error: unknown; message: string; retry?: () => void; retryLabel?: string
}) {
  const t = useT()
  const { status } = entryError(error)
  const action = retry && <Button onClick={retry}>{retryLabel ?? t('common.retry')}</Button>
  if (status === 409) return <ConflictBanner action={action}>{message}</ConflictBanner>
  if (status === 403) return <Stack><ReadOnlyNote>{message}</ReadOnlyNote>{action}</Stack>
  return <Alert tone="danger" action={action}>{message}</Alert>
}
