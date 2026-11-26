import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { RouteTranslations, useLanguage, useT } from '../../../i18n'
import { ConflictBanner, PageHeader, ReadOnlyNote } from '../../../patterns'
import type { ProjectSection, SectionSearch } from '../../../projectNavigation'
import { Alert, Button, Card, Skeleton, Stack } from '../../../ui'
import { canEdit, shipError } from '../api/ship'
import type { ShipProps, ValidationIssue } from '../api/ship'
import english from '../copy.json'
import '../ship.css'

export function ShipScreen({ name, children }: { name: string; children: ReactNode }) {
  return <RouteTranslations english={english}><ShipLayout name={name}>{children}</ShipLayout></RouteTranslations>
}

function ShipLayout({ name, children }: { name: string; children: ReactNode }) {
  const t = useT()
  return <Stack gap={5} className="v2-ship"><PageHeader title={t('ship.' + name)} description={t('ship.' + name + 'Lead')} />{children}</Stack>
}

export function useShipSearch() {
  const search = useSearch({ strict: false }) as SectionSearch
  const navigate = useNavigate({ from: '/projects/$projectId/$section' })
  function change(next: Partial<SectionSearch>, replace = false) {
    return navigate({ search: previous => ({ ...previous, ...next }), replace })
  }
  return { search, change }
}

export function ShipLink({ id, section, label, testId }: { id: string; section: ProjectSection; label: string; testId?: string }) {
  const search = useSearch({ strict: false }) as SectionSearch
  return <Button asChild><Link to="/projects/$projectId/$section" params={{ projectId: id, section }}
    search={{ preview: search.preview, workspace: search.workspace }} data-testid={testId}>{label}</Link></Button>
}

export function ShipRole({ props, children }: { props: ShipProps; children?: ReactNode }) {
  const t = useT()
  if (props.roleError) return <Alert tone="warning" action={<Button onClick={props.retryRole}>{t('common.retry')}</Button>}>{t('ship.roleError')}</Alert>
  if (!props.rolePending && !canEdit(props.role)) return <ReadOnlyNote>{children}</ReadOnlyNote>
  return null
}

export function ShipLoading({ label, lines = 5 }: { label: string; lines?: number }) {
  return <Card><Skeleton lines={lines} label={label} /></Card>
}

export function ShipProblem({ error, message, retry, testId }: { error: unknown; message: string; retry?: () => unknown; testId?: string }) {
  const t = useT()
  const status = shipError(error)?.status
  if (status === 409) return <ConflictBanner onReload={retry}>{message}</ConflictBanner>
  if (status === 403) return <Alert tone="warning">{t('behavior.forbidden')}</Alert>
  return <div data-testid={testId}><Alert tone="danger" action={retry && <Button onClick={() => void retry()}>{t('common.retry')}</Button>}>{message}</Alert></div>
}

export function useShipFormat() {
  const { language, t } = useLanguage()
  return {
    date: (value: string) => new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)),
    bytes: (value: number) => Intl.NumberFormat(language, {
      style: 'unit', unit: value >= 1_048_576 ? 'megabyte' : value >= 1024 ? 'kilobyte' : 'byte',
      maximumFractionDigits: 1,
    }).format(value >= 1_048_576 ? value / 1_048_576 : value >= 1024 ? value / 1024 : value),
    columns: (...keys: string[]) => keys.map(key => ({ id: key, label: t('ship.' + key) })),
  }
}

export function useIssueRows(issues: ValidationIssue[]) {
  const t = useT()
  return issues.map((issue, index) => ({ id: issue.path + issue.code + index, cells: [
    <code>{t('ship.value', { value: issue.path })}</code>,
    <code>{t('ship.value', { value: issue.code })}</code>,
    t('ship.value', { value: issue.message }),
  ] }))
}
