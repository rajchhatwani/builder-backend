import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { RouteTranslations, useLanguage, useT } from '../../../i18n'
import { ConflictBanner, PageHeader, ReadOnlyNote } from '../../../patterns'
import type { SectionSearch } from '../../../projectNavigation'
import { Alert, Button, Card, Skeleton, Stack } from '../../../ui'
import { errorInfo } from '../api/operate'
import type { OperateProps, ValidationIssue } from '../api/operate'
import english from '../copy.json'

export function OperateScreen({ title, lead, children }: { title: string; lead: string; children: ReactNode }) {
  return <RouteTranslations english={english}><ScreenContents title={title} lead={lead}>{children}</ScreenContents></RouteTranslations>
}

function ScreenContents({ title, lead, children }: { title: string; lead: string; children: ReactNode }) {
  const t = useT()
  return <Stack gap={5}><PageHeader title={t(title)} description={t(lead)} />{children}</Stack>
}

export function useOperateSearch() {
  const search = useSearch({ strict: false }) as SectionSearch
  const navigate = useNavigate({ from: '/projects/$projectId/$section' })
  return { search, change: (next: Partial<SectionSearch>, replace = false) =>
    void navigate({ search: (previous) => ({ ...previous, ...next }), replace }) }
}

export function SectionLink({ id, section, label, search }: { id: string; section: string; label: string; search?: SectionSearch }) {
  const current = useSearch({ strict: false }) as SectionSearch
  return <Button asChild><Link to="/projects/$projectId/$section" params={{ projectId: id, section }}
    search={{ preview: current.preview, workspace: current.workspace, ...search }}>{label}</Link></Button>
}

export function RoleNotice({ role, roleError, retryRole }: OperateProps) {
  const t = useT()
  if (roleError) return <Alert tone="warning" action={<Button onClick={retryRole}>{t('common.retry')}</Button>}>{t('operate.roleError')}</Alert>
  return role === 'viewer' ? <ReadOnlyNote /> : null
}

export function LoadState({ error, retry, label = 'operate.error', lines = 7, detail = false }: { error?: unknown; retry: () => unknown; label?: string; lines?: number; detail?: boolean }) {
  const t = useT()
  if (!error) return <Card><Skeleton lines={lines} /></Card>
  const info = errorInfo(error)
  const status = info?.status
  if (status === 403) return <Alert tone="warning">{t('behavior.forbidden')}</Alert>
  if (status === 409) return <ConflictBanner onReload={() => void retry()} />
  return <Alert tone="danger" action={<Button onClick={() => void retry()}>{t('common.retry')}</Button>}>{detail && info?.message && info.status < 500 ? t('operate.data', { value: info.message }) : t(label)}</Alert>
}

export function Issues({ issues, error, retry, prefix }: { issues?: ValidationIssue[]; error?: unknown; retry: () => unknown; prefix?: string }) {
  const t = useT()
  const entries = issues?.filter(issue => !prefix || issue.path === prefix || issue.path.startsWith(prefix + '.')) ?? []
  if (error) return <LoadState error={error} retry={retry} label={'operate.issuesError'} />
  return entries.length ? <Card><Stack><h2>{t('operate.issues')}</h2>
    <ul>{entries.map(({ path, code, message }, i) => <li key={path + code + i}>{t('operate.issue', { path, message })}</li>)}</ul>
  </Stack></Card> : null
}

export function useOperateDate() {
  const { language, t } = useLanguage()
  return (value: string | number | null | undefined) => {
    if (value == null) return t('operate.emptyValue')
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? t('operate.data', { value }) :
      new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(date)
  }
}

export function useOptions() {
  const t = useT()
  return (values: readonly string[]) => values.filter(Boolean).map(value => ({ value, label: t('operate.data', { value }) }))
}
