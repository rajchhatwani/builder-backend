import { Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { useT } from '../../../i18n'
import { ReadOnlyNote } from '../../../patterns'
import { Alert, Button, Card, Skeleton, Stack } from '../../../ui'
import { connectIssuesOptions } from '../api/blocks'
import { statusOf } from '../api/connect'
import type { ConnectRole } from '../api/connect'

export function SectionLink({ projectId, section, label, preview, workspace }: { projectId: string; section: string; label: string; preview?: string; workspace?: string }) {
  return <Button asChild><Link to="/projects/$projectId/$section" params={{ projectId, section }} search={{ preview, workspace }}>{label}</Link></Button>
}

export function BlockLoad({ error, retry, errorKey }: { error: unknown; retry: () => void; errorKey: string }) {
  const t = useT()
  if (!error) return <Card><Skeleton lines={7} /></Card>
  if ([403, 404].includes(statusOf(error) ?? 0)) return <Alert tone="warning">{t('behavior.forbidden')}</Alert>
  return <Alert tone="danger" action={<Button onClick={retry}>{t('common.retry')}</Button>}>{t(errorKey)}</Alert>
}

export function BlockRole({ role, roleError, retryRole }: ConnectRole) {
  const t = useT()
  if (roleError) return <Alert tone="danger" action={<Button onClick={retryRole}>{t('common.retry')}</Button>}>{t('connectA2.roleError')}</Alert>
  return role === 'viewer' ? <ReadOnlyNote /> : null
}

export function Issues({ id, block }: { id: string; block: string }) {
  const t = useT()
  const query = useQuery(connectIssuesOptions(id))
  const issues = query.data?.issues.filter(issue => issue.path === block || issue.path.startsWith(block + '.') ||
    block === 'webhooks' && issue.code.startsWith('webhook_job_')) ?? []
  if (query.isError) return <Alert tone="warning" action={<Button onClick={() => void query.refetch()}>{t('common.retry')}</Button>}>{t('connectA2.issuesError')}</Alert>
  if (!issues.length) return null
  return <Card><Stack><h2>{t('connectA2.issues')}</h2>
    <ul>{issues.map(({ path, code, message }, index) => <li key={path + code + index}>{t('connectA2.issue', { path, message })}</li>)}</ul>
  </Stack></Card>
}
