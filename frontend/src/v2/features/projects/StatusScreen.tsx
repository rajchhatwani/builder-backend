import { Link, useParams } from '@tanstack/react-router'
import { useT } from '../../i18n'
import { ConflictBanner, ListRow, PageHeader, ReadOnlyNote, StatusPill } from '../../patterns'
import { statusSection } from '../../projectNavigation'
import type { ProjectSection } from '../../projectNavigation'
import { Alert, Button, Card, EmptyState, Grid, Row, Skeleton, Stack, useToast } from '../../ui'
import { statusCode, useProjectStatus, useStepMutation } from './api/status'

const countNames = ['entities', 'relations', 'state_machines', 'settings', 'sequences', 'lists', 'history_configs', 'hooks', 'seed_profiles'] as const
const steps = ['fix_issues', 'add_entity', 'consider_auth', 'generate']

function issueDestination({ path, code }: { path: string; code: string }): ProjectSection {
  if (/^auth\.keycloak(?:\.|\[|$)/.test(path)) return 'keycloak'
  if (code === 'storage_required') return 'storage'
  if (code.startsWith('authz.') || /^auth\.(roles|permissions)(?:\.|\[|$)/.test(path)) return 'access'
  const root = path.split(/[.[]/, 1)[0]
  if (root === 'lists' || root === 'sequences') return 'settings'
  return statusSection(root)
}

export default function StatusScreen() {
  const { projectId = '' } = useParams({ strict: false })
  const t = useT()
  const toast = useToast()
  const query = useProjectStatus(projectId)
  const mutation = useStepMutation(projectId)
  const heading = <PageHeader title={t('status.title')} description={t('status.intro')} />

  function go(section: ProjectSection, label: string, ariaLabel?: string) {
    return <Button asChild><Link to="/projects/$projectId/$section" params={{ projectId, section }} aria-label={ariaLabel}>{label}</Link></Button>
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
          ? <EmptyState title={t(code === 404 ? 'status.missing' : 'status.forbidden')} action={<Button asChild><a href="/projects">{t('status.back')}</a></Button>} />
          : <Alert tone="danger" action={<Button onClick={() => void query.refetch()}>{t('common.retry')}</Button>}>{t('status.loadError')}</Alert>}
      </Stack>
    )
  }

  const { ready, counts, issues, sections, next_step: next, dismissed_steps: dismissed = [] } = query.data
  const readOnly = statusCode(mutation.error) === 403
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
      <Alert tone={ready ? 'success' : 'warning'}>{t(ready ? 'status.ready' : 'status.blocked')}</Alert>
      <Card>
        <Stack>
          <span className="v2-muted v2-small">{t('status.nextStep')}</span>
          <h2>{t('common.serverText', { text: next.title })}</h2>
          <p>{t('common.serverText', { text: next.reason })}</p>
          <Row>
            {go(statusSection(next.section), t(`status.action.${next.id}`))}
            {next.id === 'consider_auth' && !readOnly && (
              <Button disabled={mutation.isPending} onClick={() => run(next.id, false)}>{t('status.notNow')}</Button>
            )}
          </Row>
          {mutation.isError && !conflict && !readOnly && <Alert tone="danger">{t(mutation.variables?.restore ? 'status.restoreError' : 'status.dismissError')}</Alert>}
        </Stack>
      </Card>
      {next.id === 'add_entity' && <EmptyState title={t('status.empty')} action={go('model', t('status.action.add_entity'))} />}
      {issues.length > 0 && (
        <Stack gap={2}>
          <h2>{t('status.issues')}</h2>
          <Card><Stack gap={3}>{issues.map((issue, index) => (
            <ListRow key={`${issue.path}:${issue.code}:${index}`} title={t('common.serverText', { text: issue.message })}
              detail={<code className="v2-mono">{t('status.issueReference', { path: issue.path, code: issue.code })}</code>}
              actions={go(issueDestination(issue), t('status.fix'), t('status.fixIssue', { issue: issue.message }))} />
          ))}</Stack></Card>
        </Stack>
      )}
      {dismissed.length > 0 && (
        <Stack gap={2}>
          <h2>{t('status.dismissedSteps')}</h2>
          <Card><Stack>{dismissed.map(step => <ListRow key={step.id} title={t('common.serverText', { text: step.title })}
            detail={t('common.serverText', { text: step.reason })} actions={!readOnly && (
              <Button disabled={mutation.isPending} onClick={() => run(step.id, true)}>{t('status.showAgain')}</Button>
            )} />)}</Stack></Card>
        </Stack>
      )}
      <Stack gap={2}>
        <h2>{t('status.sections')}</h2>
        <Grid gap={2}>
          {sections.map(section => {
            const label = t('common.serverText', { text: section.label })
            return (
              <Card key={section.id}>
                <Stack gap={2}>
                  <h3>{label}</h3>
                  <StatusPill tone={section.issue_count ? 'danger' : section.configured ? 'success' : 'neutral'}>
                    {section.issue_count ? t('status.problems', { count: section.issue_count }) : t(section.configured ? 'status.configured' : 'status.unconfigured')}
                  </StatusPill>
                  <Row>{go(statusSection(section.id), t(section.configured ? 'status.open' : 'status.setup'),
                    t(section.configured ? 'status.openSection' : 'status.setupSection', { label }))}</Row>
                </Stack>
              </Card>
            )
          })}
        </Grid>
      </Stack>
      <Stack gap={2}>
        <h2>{t('status.counts')}</h2>
        <Row>{countNames.filter(name => counts[name] !== undefined).map(name => (
          <StatusPill key={name} tone="neutral">{t(`status.count.${name}`, { count: counts[name] })}</StatusPill>
        ))}</Row>
      </Stack>
      <Stack gap={2}>
        <h2>{t('status.path')}</h2>
        <ol className="v2-step-list">
          {steps.map(step => <li key={step} aria-current={step === next.id ? 'step' : undefined}>{t(`status.action.${step}`)}</li>)}
        </ol>
      </Stack>
    </Stack>
  )
}
