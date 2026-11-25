import { useQuery } from '@tanstack/react-query'
import { Link, useSearch } from '@tanstack/react-router'
import { useT } from '../../i18n'
import { ListRow } from '../../patterns'
import { defaultSectionSearch } from '../../projectNavigation'
import { Alert, Badge, Button, Card, Skeleton, Stack } from '../../ui'
import { checklistOptions } from './api/workspace'

export function SetupChecklist({ projectId, auth, keycloak, keycloakSaved, configured, entities }: {
  projectId: string; auth: boolean; keycloak?: boolean; keycloakSaved: boolean; configured: ReadonlySet<string>; entities: number
}) {
  const t = useT()
  const { preview } = useSearch({ strict: false })
  const extra = useQuery(checklistOptions(projectId, true))
  const generations = extra.data?.generations
  const roles = extra.data?.roles
  const rows = [
    { id: 'model', done: entities > 0, action: entities ? 'edit' : 'start', detail: entities ? t('checklist.entities', { count: entities }) : t('checklist.modelBody') },
    { id: 'auth', done: auth, optional: true, action: auth ? 'edit' : 'setup', detail: t(keycloak ? 'checklist.authKeycloak' : auth ? 'checklist.authOn' : 'checklist.authBody') },
    { id: 'keycloak', done: keycloak, optional: true, action: keycloak ? 'edit' : keycloakSaved ? 'turnOn' : 'setup', detail: t(keycloak ? 'checklist.keycloakOn' : 'checklist.keycloakBody') },
    ...(['payments', 'storage'] as const).map(id => ({
      id, done: configured.has(id), optional: true, action: configured.has(id) ? 'edit' : extra.data?.[id] ? 'turnOn' : 'setup',
      detail: t('checklist.' + id + (configured.has(id) ? 'On' : 'Body')),
    })),
    ...(auth ? [{ id: 'access', done: roles === undefined ? configured.has('authorization') : roles > 0, action: roles ? 'edit' : 'setup',
      detail: roles ? t('checklist.roles', { count: roles }) : t('checklist.accessBody') }] : []),
    { id: 'generate', done: Boolean(generations), action: generations ? 'open' : 'generate', detail: generations
      ? t('checklist.downloads', { count: generations }) : t('checklist.generateBody') },
  ]
  return <Stack gap={2}>
    <h2>{t('checklist.title')}</h2>
    <p className="v2-muted">{t('checklist.intro')}</p>
    {extra.isError && <Alert tone="warning" action={<Button onClick={() => void extra.refetch()}>{t('common.retry')}</Button>}>{t('checklist.error')}</Alert>}
    <Card>{extra.isPending ? <Skeleton label={t('checklist.loading')} lines={rows.length} /> : <Stack>
      {rows.map(row => <ListRow key={row.id}
        title={t('checklist.step.' + row.id)}
        detail={<span>
          <Badge tone={row.done ? 'success' : 'neutral'}>{t(row.done ? 'checklist.done' : 'checklist.todo')}</Badge>{' '}
          {row.optional && <><Badge>{t('checklist.optional')}</Badge>{' '}</>}{row.detail}
        </span>}
        actions={<Button asChild><Link to="/projects/$projectId/$section" params={{ projectId, section: row.id }}
          aria-label={t('checklist.actionLabel', { action: t('checklist.action.' + row.action), title: t('checklist.step.' + row.id) })}
          search={{ ...defaultSectionSearch(row.id), preview }}>{t('checklist.action.' + row.action)}</Link></Button>} />)}
    </Stack>}</Card>
  </Stack>
}
