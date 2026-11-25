import { Link } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLanguage, useT } from '../../../i18n'
import { ConfirmDestructive, ReadOnlyNote } from '../../../patterns'
import { Badge, Button, Card, Row, Stack, useToast } from '../../../ui'
import { entryError } from '../api/entry'
import { projectDetailOptions, projectHealthOptions, projectKeys, projectMemberOptions, projectsApi } from '../api/projects'
import type { Organization, Project } from '../api/projects'
import { formatEntryDate, projectLocked } from './entryData'
import { authProblem } from './messages'

export function ProjectRow({ project, org, userId, sessionMfa }: {
  project: Project; org?: Organization; userId: string; sessionMfa: boolean
}) {
  const t = useT()
  const { language } = useLanguage()
  const toast = useToast()
  const client = useQueryClient()
  const locked = projectLocked(project, org)
  const needsMfa = Boolean(org?.require_mfa && !sessionMfa)
  const open = !locked && !needsMfa
  const details = useQuery({ ...projectDetailOptions(project.id), enabled: open })
  const members = useQuery({ ...projectMemberOptions(project.id), enabled: open })
  const role = members.data?.find(member => member.user_id === userId)?.role
  const health = useQuery({ ...projectHealthOptions(project.id, role === 'viewer'), enabled: open && Boolean(role) })
  const remove = useMutation({
    mutationFn: () => projectsApi.remove(project.id),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: projectKeys.lists() })
      void client.invalidateQueries({ queryKey: projectKeys.plan(org?.slug ?? '') })
      toast({ title: t('projectList.deleted', { name: project.name }), tone: 'success' })
    },
  })
  const updated = formatEntryDate(project.updated_at, language, t('common.unavailable'))
  const issueCount = health.data?.issues.length ?? 0
  const auth = details.data?.signIn
  const entities = details.data?.entities
  const summary = entities === undefined || auth === undefined
    ? t(details.isPending ? 'common.loading' : 'projectList.summaryUnavailable')
    : t('projectList.summary', {
      entities: entities ? t('projectList.entities', { count: entities }) : t('projectList.noEntities'),
      auth: t(auth ? 'projectList.authOn' : 'projectList.authOff'),
    })

  function openProject(label: string, button = false) {
    const link = <Link to="/projects/$projectId/overview" params={{ projectId: project.id }}>{label}</Link>
    return button ? <Button asChild>{link}</Button> : link
  }

  return <Card><Stack gap={2}>
    <Row className="v2-spread">
      <Row>
        <h2>{open ? openProject(project.name) : project.name}</h2>
        {locked || needsMfa ? <Badge tone="warning">{t(locked ? 'projectList.locked' : 'projectList.needsMfa')}</Badge>
          : health.data ? <Badge tone={health.data.valid ? 'success' : 'warning'}>{t(health.data.valid ? 'shell.ready' : 'projectList.toFix', { count: issueCount })}</Badge>
            : health.isError && <Button onClick={() => void health.refetch()}>{t('projectList.retryHealth')}</Button>}
      </Row>
      {open && <Row>
        {openProject(t('projectList.open'), true)}
        {role === 'owner' && <ConfirmDestructive
          trigger={<Button variant="danger" onClick={() => remove.reset()}>{t('projectList.delete')}</Button>}
          title={t('projectList.deleteTitle', { name: project.name })} description={t('projectList.deleteHelp')}
          action={t('projectList.deleteAction')} onConfirm={async () => { await remove.mutateAsync() }}
          error={remove.isError ? t(entryError(remove.error).status === 403 ? 'projectList.ownerOnly' : authProblem(remove.error)) : undefined}
        />}
      </Row>}
    </Row>
    {project.description && <p>{project.description}</p>}
    {open ? <Stack gap={1}>
      <Row className="v2-muted v2-small">
        <span>{org?.name ?? t('projectList.ownerUnknown')}</span>
        <code>{project.slug}</code>
        <span>{summary}</span>
        {members.data && <span>{t('projectList.members', { count: members.data.length })}</span>}
        <span>{t('projectList.updated', { date: updated })}</span>
        {details.data?.generation !== undefined && <span>{details.data.generation
          ? t('projectList.generated', { date: formatEntryDate(details.data.generation.created_at, language, t('common.unavailable')) })
          : t('projectList.noGeneration')}</span>}
      </Row>
      {role === 'viewer' && <ReadOnlyNote />}
      {members.isError && <Row><Button onClick={() => void members.refetch()}>{t('projectList.retryAccess')}</Button></Row>}
    </Stack> : <Stack>
      <ReadOnlyNote>{locked
        ? (project.organization_deletion_scheduled_for || org?.deletion_scheduled_for)
          ? t('projectList.lockedDated', {
            org: org?.name ?? t('projectList.thisOrg'), date: formatEntryDate(project.organization_deletion_scheduled_for ?? org?.deletion_scheduled_for, language, ''),
          })
          : t('projectList.lockedUndated', { org: org?.name ?? t('projectList.thisOrg') })
        : t('projectList.mfaNote', { org: org?.name ?? t('projectList.thisOrg') })}</ReadOnlyNote>
      <Row>{locked ? org && <Button asChild><Link to="/org/$slug" params={{ slug: org.slug }}>{t('projectList.openOrg')}</Link></Button>
        : <Button asChild><Link to="/account">{t('projectList.openAccount')}</Link></Button>}</Row>
    </Stack>}
  </Stack></Card>
}
