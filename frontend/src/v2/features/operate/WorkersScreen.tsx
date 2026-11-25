import { useQuery } from '@tanstack/react-query'
import { unservedQueues } from '../../../shell/connect/blockLogic'
import { useT } from '../../i18n'
import { SettingsSection } from '../../patterns'
import { Alert, Badge, Card, Disclosure, EmptyState, Grid, Row, Stack, Table } from '../../ui'
import { advisorOptions, issuesOptions, workerSpecOptions } from './api/operate'
import type { OperateProps } from './api/operate'
import { Issues, LoadState, OperateScreen, SectionLink } from './components/Common'
import './operate.css'

export default function WorkersScreen({ projectId }: OperateProps) {
  return <OperateScreen title={'operate.workers.title'} lead="operate.workers.lead"><Workers id={projectId} /></OperateScreen>
}

function Workers({ id }: { id: string }) {
  const t = useT()
  const query = useQuery(workerSpecOptions(id))
  const issues = useQuery(issuesOptions(id))
  const advisor = useQuery(advisorOptions(id))
  const jobs = query.data?.jobs
  const workflows = query.data?.workflows
  const groups = jobs?.worker_groups ?? []
  const waiting = unservedQueues(jobs)
  const columns = (keys: string[]) => keys.map(key => ({ id: key, label: t('operate.workers.' + key) }))
  const value = (value: string | number) => t('operate.data', { value })
  const jobsLink = <SectionLink id={id} section="jobs" label={t('operate.jobs.title')} />
  if (!query.data) return <LoadState error={query.error} retry={query.refetch} />
  return <Stack gap={4}>
    <Row>{jobsLink}<SectionLink id={id} section="workflows" label={t('operate.flows.title')} /></Row>
    <Grid>{([
      ['slots', jobs?.enabled ? groups.reduce((sum, group) => sum + (group.concurrency ?? 4), 0) : 0],
      ['unserved', waiting.length],
      ['workflowSlots', workflows?.enabled ? workflows.worker?.concurrency ?? 2 : 0],
    ] as const).map(([key, count]) => <Card key={key}><Stack gap={1}><p>{t('operate.workers.' + key)}</p><strong>{value(count)}</strong></Stack></Card>)}</Grid>
    <Issues issues={issues.data?.issues.filter(issue => /^jobs\.(worker_groups|queue)(\b|\[)/.test(issue.path))}
      error={issues.error} retry={issues.refetch} />
    {waiting.length > 0 && <Alert tone="warning">{t('operate.jobs.unserved', { names: waiting.join(', ') })}</Alert>}
    {!jobs?.enabled ? <EmptyState title={t('operate.workers.off')} description={t('operate.workers.offHint')} action={jobsLink} /> : <>
      <SettingsSection title={t('operate.workers.groups')}>
        <Table label={t('operate.workers.groups')} columns={columns(['group', 'queues', 'concurrency', 'placement'])}
          rows={groups.map((group, index) => ({
            id: group.name + index, cells: [value(group.name), value((group.queues ?? ['default']).join(', ')), value(group.concurrency ?? 4),
              group.placement === 'separate_server' ? t('operate.workers.separate_server') : t('operate.workers.same_server')],
          }))} />
        {!groups.length && jobsLink}
      </SettingsSection>
      <SettingsSection title={t('operate.workers.technology')} description={t('operate.workers.backend', { backend: jobs.queue?.backend ?? 'postgres' })}>
        {(jobs.queue?.backend ?? 'postgres') === 'postgres' && <p>{t('operate.workers.topology')}</p>}
        <p>{t('operate.workers.artifacts')}</p>
        <Disclosure label={t('operate.workers.deployment')}><Stack gap={1}>
          <p>{t('operate.workers.environment')}</p>
          <p>{t('operate.workers.pool')}</p>
          <p>{t('operate.workers.deadJobs')}</p>
        </Stack></Disclosure>
      </SettingsSection>
      {Boolean(jobs.jobs?.length) && <SettingsSection title={t('operate.workers.coverage')}>
        <Table label={t('operate.workers.coverage')} columns={columns(['queue', 'job', 'served', 'handler', 'timeout', 'retry'])}
          rows={(jobs.jobs ?? []).map((job, index) => ({
            id: job.name + index,
            cells: [value(job.queue ?? 'default'), value(job.name), value(groups.filter(group =>
              (group.queues ?? ['default']).includes(job.queue ?? 'default')).map(group => group.name).join(', ') || t('operate.none')),
            value(job.handler), t('operate.workers.seconds', { count: job.timeout_seconds ?? 300 }),
            t('operate.workers.retryValue', { count: job.retry?.max_attempts ?? 3, mode: job.retry?.backoff ?? 'exponential', wait: job.retry?.backoff_seconds ?? 30 })],
          }))} />
      </SettingsSection>}
      {Boolean(jobs.schedules?.length) && <SettingsSection title={t('operate.workers.schedules')}>
        <Table label={t('operate.workers.schedules')} columns={columns(['schedule', 'job', 'status'])} rows={(jobs.schedules ?? []).map((schedule, index) => ({
          id: schedule.name + index, cells: [<Stack gap={1}><strong>{value(schedule.name)}</strong><code>{value(schedule.cron)}</code>
            <span>{value(schedule.timezone ?? 'UTC')}</span></Stack>, value(schedule.job),
          <Badge tone={schedule.enabled !== false ? 'success' : 'neutral'}>{t(schedule.enabled !== false ? 'operate.on' : 'operate.off')}</Badge>],
        }))} />
      </SettingsSection>}
    </>}
    <SettingsSection title={t('operate.workers.workflow')}>
      <p>{workflows?.enabled ? t('operate.workers.workflowInfo', { runtime: workflows.runtime ?? 'postgres', count: workflows.worker?.concurrency ?? 2 }) :
        t('operate.workers.workflowOff')}</p>
    </SettingsSection>
    <SettingsSection title={t('operate.workers.advisor')} description={t('operate.workers.advisorHelp')}>
      {!advisor.data ? <LoadState error={advisor.error} retry={advisor.refetch} label={'operate.workers.adviceError'} lines={3} /> : <Grid>
        <Advice title={t('operate.workers.queueAdvice')} data={advisor.data.queue} />
        <Advice title={t('operate.workers.workflowAdvice')} data={advisor.data.workflow} />
      </Grid>}
    </SettingsSection>
  </Stack>
}

function Advice({ title, data }: { title: string; data?: Record<string, unknown> | null }) {
  const t = useT()
  return <Card><Stack><h3>{title}</h3>
    {!data ? <p>{t('operate.none')}</p> : <dl className="v2-operate-kv">{Object.entries(data).map(([key, item]) =>
      <div key={key}><dt>{t('operate.workers.' + key)}</dt><dd>{Array.isArray(item) ? item.length ?
        <ul>{item.map((text, index) => <li key={index}>{t('operate.data', { value: String(text) })}</li>)}</ul> : t('operate.none') :
        typeof item === 'boolean' ? t(item ? 'operate.workers.yes' : 'operate.workers.no') :
          t('operate.data', { value: String(item) })}</dd></div>)}</dl>}
  </Stack></Card>
}
