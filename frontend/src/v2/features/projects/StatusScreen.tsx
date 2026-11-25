import { useQuery } from '@tanstack/react-query'
import { useContext } from 'react'
import { Link, useParams, useSearch } from '@tanstack/react-router'
import { useT } from '../../i18n'
import { ConflictBanner, ListRow, PageHeader, ReadOnlyNote, StatusPill } from '../../patterns'
import { defaultSectionSearch, statusSection } from '../../projectNavigation'
import type { ProjectSection } from '../../projectNavigation'
import { Alert, Button, Card, EmptyState, Grid, Row, Skeleton, Stack, useToast } from '../../ui'
import { statusCode, useProjectStatus, useStepMutation } from './api/status'
import { keycloakOptions } from './api/workspace'
import { SetupChecklist } from './SetupChecklist'
import { WorkspaceContext } from './workspaceContext'

const countNames = ['entities', 'relations', 'state_machines', 'settings', 'sequences', 'lists', 'history_configs', 'hooks', 'seed_profiles'] as const
const steps = ['fix_issues', 'add_entity', 'consider_auth', 'generate']
const statusAreas = new Set([
  'model', 'auth', 'payments', 'storage', 'authorization', 'observability', 'deployment', 'documents',
  'state_machines', 'settings', 'history', 'hooks', 'seed',
])

function issueArea({ path, code }: { path: string; code: string }): ProjectSection {
  if (code === 'storage_required') return 'storage'
  if (code.startsWith('authz.') || path.startsWith('auth.roles') || path.startsWith('auth.permissions')) return 'access'
  const root = path.split(/[.[]/, 1)[0]
  if (root === 'lists' || root === 'sequences') return 'settings'
  return statusAreas.has(root) ? statusSection(root) : 'model'
}

function issueDestination(issue: { path: string; code: string }) {
  return /^auth\.keycloak(?:\.|\[|$)/.test(issue.path) ? 'keycloak' : issueArea(issue)
}

const countRoutes = {
  entities: 'model', relations: 'model', state_machines: 'machines', settings: 'settings', sequences: 'settings',
  lists: 'settings', history_configs: 'history', hooks: 'hooks', seed_profiles: 'seed',
} as const

export default function StatusScreen() {
  const { projectId = '' } = useParams({ strict: false })
  const { preview } = useSearch({ strict: false })
  const t = useT()
  const toast = useToast()
  const query = useProjectStatus(projectId)
  const mutation = useStepMutation(projectId)
  const workspace = useContext(WorkspaceContext)
  const auth = Boolean(query.data?.sections?.find(section => section.id === 'auth')?.configured)
  const keycloak = useQuery(keycloakOptions(projectId, Boolean(query.data)))
  const heading = <PageHeader title={t('status.title')} description={t('status.intro')} />

  function go(section: ProjectSection, label: string, ariaLabel?: string) {
    return <Button asChild><Link to="/projects/$projectId/$section" params={{ projectId, section }} search={{ ...defaultSectionSearch(section), preview }} aria-label={ariaLabel}>{label}</Link></Button>
  }

  if (!query.data && query.isPending) return (
    <Stack gap={5}>
      {heading}
      <Card><Skeleton lines={5} label={t('status.loading')} /></Card>
      <Grid gap={2} aria-hidden>
        {Array.from({ length: 13 }, (_, index) => <Card key={index}><Skeleton /></Card>)}
      </Grid>
    </Stack>
  )
  if (!query.data) {
    const code = statusCode(query.error)
    return (
      <Stack gap={5}>{heading}
        {code === 409 ? <ConflictBanner onReload={() => void query.refetch()} /> : code === 401 || code === 403 || code === 404
          ? <EmptyState title={t(code === 404 ? 'status.missing' : 'status.forbidden')} action={<Button asChild><Link to="/projects" search={{}}>{t('status.back')}</Link></Button>} />
          : <Alert tone="danger" action={<Button onClick={() => void query.refetch()}>{t('common.retry')}</Button>}>{t('status.loadError')}</Alert>}
      </Stack>
    )
  }

  const { ready, counts, issues, sections, next_step: next, dismissed_steps: dismissed = [] } = query.data
  const writable = workspace.role === 'owner' || workspace.role === 'editor'
  const readOnly = (!workspace.rolePending && !writable) || statusCode(mutation.error) === 403
  const canEdit = writable && !readOnly
  const configured = new Set(sections.filter(section => section.configured).map(section => section.id))
  const mutationError = mutation.isError && statusCode(mutation.error) !== 409 && statusCode(mutation.error) !== 403
  const readiness = ready ? t('status.readyBody') : issues.length
    ? t('status.blockedIssues', { count: issues.length }) : t('status.blockedEmpty')
  const conflict = statusCode(mutation.error) === 409
  const run = (step: string, restore: boolean) => mutation.mutate({ step, restore }, {
    onSuccess: () => toast({ title: t(restore ? 'status.restored' : 'status.dismissed'), tone: 'success' }),
  })
  return (
    <Stack gap={5}>
      {heading}
      {query.isError && <Alert tone="danger" action={<Button onClick={() => void query.refetch()}>{t('common.retry')}</Button>}>{t('status.loadError')}</Alert>}
      {readOnly && <ReadOnlyNote>{t('status.readOnly')}</ReadOnlyNote>}
      {conflict && <ConflictBanner onReload={() => { mutation.reset(); void query.refetch() }} />}
      {workspace.roleError && <Alert tone="warning" action={<Button onClick={workspace.retryRole}>{t('common.retry')}</Button>}>{t('status.roleError')}</Alert>}
      {keycloak.isError && <Alert tone="warning" action={<Button onClick={() => void keycloak.refetch()}>{t('common.retry')}</Button>}>{t('status.keycloakError')}</Alert>}
      <Alert tone={ready ? 'success' : 'warning'}>
        <Stack gap={1} data-testid="readiness-banner" data-ready={String(ready)}>
          <Row className="v2-spread" gap={2}>
            <strong>{t(ready ? 'status.ready' : 'status.blocked')}</strong>
            {workspace.project && workspace.version !== undefined && <small>{t(workspace.organization ? 'status.projectOrg' : 'status.projectVersion',
              { project: workspace.project, organization: workspace.organization ?? '', version: workspace.version })}</small>}
          </Row>
          <p>{readiness}</p>
        </Stack>
      </Alert>
      <Card>
        <Stack data-testid="next-step" data-step-id={next.id}>
          <span className="v2-muted v2-small">{t('status.nextStep')}</span>
          <h2>{t('common.serverText', { text: next.title })}</h2>
          <p>{t('common.serverText', { text: next.reason })}</p>
          <Row>
            {go(next.id === 'fix_issues' && issues[0] ? issueDestination(issues[0]) : statusSection(next.section),
              steps.includes(next.id) ? t(`status.action.${next.id}`) : t('status.open'))}
            {next.id === 'consider_auth' && !next.dismissed && canEdit && (
              <Button disabled={mutation.isPending} onClick={() => run(next.id, false)}>{t('status.notNow')}</Button>
            )}
          </Row>
        </Stack>
      </Card>
      {mutationError && <Alert tone="danger" action={mutation.variables && canEdit && <Button onClick={() => {
        if (mutation.variables) run(mutation.variables.step, mutation.variables.restore)
      }}>{t('common.retry')}</Button>}>{t(mutation.variables?.restore ? 'status.restoreError' : 'status.dismissError')}</Alert>}
      {next.id === 'add_entity' && <EmptyState title={t('status.empty')} action={go('model', t('status.action.add_entity'))} />}
      {dismissed.length > 0 && (
        <Stack gap={2}>
          <h2>{t('status.dismissedSteps')}</h2>
          <Card><Stack>{dismissed.map(step => <ListRow key={step.id} title={t('common.serverText', { text: step.title })}
            detail={t('common.serverText', { text: step.reason })} actions={canEdit && step.id === 'consider_auth' && step.dismissed !== false && (
              <Button disabled={mutation.isPending} onClick={() => run(step.id, true)}>{t('status.showAgain')}</Button>
            )} />)}</Stack></Card>
        </Stack>
      )}
      {issues.length > 0 && (
        <Stack gap={2} data-testid="home-issues">
          <h2>{t('status.issues')}</h2>
          <Card><Stack gap={3}>{issues.map((issue, index) => (
            <ListRow key={`${issue.path}:${issue.code}:${index}`} title={t('common.serverText', { text: issue.message })}
              detail={<code className="v2-mono">{t('status.issueReference', { path: issue.path, code: issue.code })}</code>}
              actions={go(issueDestination(issue), t('status.fix'), t('status.fixIssue', { issue: issue.message }))} />
          ))}</Stack></Card>
        </Stack>
      )}
      <Stack gap={2}>
        <h2>{t('status.sections')}</h2>
        <Grid gap={2} data-testid="home-sections">
          {sections.map(section => {
            const label = t('common.serverText', { text: section.label })
            const destination = statusSection(section.id)
            const related = issues.filter(issue => issueArea(issue) === destination)
            return (
              <Card key={section.id} data-testid={'home-section-' + section.id}>
                <Stack gap={2}>
                  <Row className="v2-spread" gap={1}><h3>{label}</h3>
                  <StatusPill tone={section.issue_count ? 'danger' : section.configured ? 'success' : 'neutral'}>
                    {section.issue_count ? t('status.problems', { count: section.issue_count }) : t(section.configured ? 'status.configured' : 'status.unconfigured')}
                  </StatusPill></Row>
                  {section.id === 'auth' && auth && keycloak.isSuccess && <small className="v2-muted">
                    {t(keycloak.data?.active ? 'status.keycloak' : 'status.builtIn')}
                  </small>}
                  {related.length > 0 && <details><summary className="v2-status-disclosure">{t('status.viewProblems')}</summary>
                    <Stack gap={2}>{related.map((issue, index) => <ListRow key={index}
                      title={t('common.serverText', { text: issue.message })}
                      actions={go(issueDestination(issue), t('status.fix'), t('status.fixIssue', { issue: issue.message }))} />)}</Stack>
                  </details>}
                  <Row>{go(destination, t(section.configured ? 'status.open' : 'status.setup'),
                    t(section.configured ? 'status.openSection' : 'status.setupSection', { label }))}</Row>
                </Stack>
              </Card>
            )
          })}
        </Grid>
      </Stack>
      <Stack gap={2}>
        <h2>{t('status.counts')}</h2>
        <Grid data-testid="home-counts" className="v2-status-counts" gap={2}>{countNames.filter(name => counts[name] !== undefined).map(name => (
          <div key={name}>{go(countRoutes[name], t(`status.count.${name}`, { count: counts[name] }))}</div>
        ))}</Grid>
      </Stack>
      <Stack gap={2}>
        <h2>{t('status.path')}</h2>
        <ol className="v2-step-list">
          {steps.map(step => <li key={step} aria-current={step === next.id ? 'step' : undefined}>{t(`status.pathStep.${step}`)}</li>)}
        </ol>
      </Stack>
      <SetupChecklist projectId={projectId} entities={counts.entities ?? 0} auth={auth}
        keycloak={keycloak.data?.active} keycloakSaved={Boolean(keycloak.data)} configured={configured} />
    </Stack>
  )
}
