import { useQuery } from '@tanstack/react-query'
import { danglingSchedules, unservedQueues, workflowJobProblems } from '../../../../shell/connect/blockLogic'
import { useT } from '../../../i18n'
import { jobValidation, workflowValidation } from '../../../validators/operate'
import { Alert, Disclosure, EmptyState, Stack } from '../../../ui'
import { blockOptions, canWrite, issuesOptions, rolesOptions, useBlockWrite } from '../api/operate'
import type { OperateProps, SpecJobs } from '../api/operate'
import { jobsSchema, withDefaults, workflowSchema } from '../state/schemas'
import { Issues, LoadState, useOptions } from './Common'
import { EnableAction, VersionedSettings } from './VersionedSettings'

export function JobSettings(props: OperateProps & { kind: 'jobs' | 'workflows' }) {
  const { projectId: id, kind } = props
  const t = useT()
  const pick = useOptions()
  const workflow = kind === 'workflows'
  const key = workflow ? 'operate.flows.' : 'operate.jobs.'
  const schema = workflow ? workflowSchema : jobsSchema
  const query = useQuery(blockOptions(id, kind))
  const issues = useQuery(issuesOptions(id))
  const jobs = useQuery({ ...blockOptions(id, 'jobs'), enabled: workflow })
  const roles = useQuery({ ...rolesOptions(id), enabled: workflow })
  const mutation = useBlockWrite(id, kind)
  const read = query.data
  const writable = canWrite(props)
  if (!read) return <LoadState error={query.error} retry={query.refetch} />
  const base = withDefaults(schema, kind === 'jobs' ? read.jobs ?? undefined : read.workflows ?? undefined) as Record<string, unknown>
  const related = jobs.data?.jobs
  const jobNames = related?.enabled ? related.jobs?.map(job => job.name) ?? [] : []
  return <Stack>
    <Issues issues={issues.data?.issues} error={issues.error} retry={issues.refetch} prefix={kind} />
    {workflow && jobs.isError && <LoadState error={jobs.error} retry={jobs.refetch} />}
    {workflow && roles.isError && <LoadState error={roles.error} retry={roles.refetch} />}
    <VersionedSettings title={t(key + 'config')} schema={schema} base={base} version={read.version} updatedAt={read.updated_at}
      readOnly={!writable} pending={mutation.isPending} error={mutation.error} saved={mutation.isSuccess}
      loadError={query.isRefetchError ? query.error : undefined} prefix={kind}
      reload={async () => { const result = await query.refetch(); if (result.isSuccess) mutation.reset(); return result.isSuccess }}
      save={(value, version) => mutation.mutateAsync({ value, version })}
      validate={value => workflow ? workflowValidation(value, t, jobs.data ? jobNames : undefined) : jobValidation(value, t)}
      options={(path, value) => {
        const field = path.at(-1)
        if (!workflow && path[0] === 'schedules' && field === 'job') return pick((value as SpecJobs).jobs?.map(job => job.name) ?? [])
        if (!workflow && path[0] === 'worker_groups' && path[2] === 'queues' && typeof field === 'number') {
          return pick([...new Set((value as SpecJobs).jobs?.map(job => job.queue || 'default') ?? [])])
        }
        if (workflow && field === 'job' && jobs.data) return pick(jobNames)
        if (workflow && path[2] === 'roles' && typeof field === 'number' && roles.data) return pick(roles.data.roles.map(role => role.name))
        if (field === 'backend' || field === 'runtime') {
          return pick(field === 'backend' ? ['postgres', 'redis', 'rabbitmq'] : ['postgres', 'dbos', 'temporal'])
            .map(option => ({ ...option, disabled: option.value !== 'postgres' }))
        }
      }}
      aside={() => <Stack>{workflow ? <p>{t('operate.flows.order')}</p> : <>
        <p>{t('operate.jobs.handler')}</p>
        <Disclosure label={t('operate.workers.schedule')}><p>{t('operate.jobs.cron')}</p></Disclosure>
      </>}</Stack>}>
      {(current, enable) => {
        if (!current.enabled) return <EmptyState title={t(key + 'off')} description={t(key + 'offHint')}
          action={writable && <EnableAction onClick={enable} />} />
        if (workflow) {
          const dangling = workflowJobProblems(current, related)
          return dangling.length > 0 && jobs.data && <Alert tone="warning">{t('operate.flows.jobProblem', { names: dangling.join(', ') })}</Alert>
        }
        const queues = unservedQueues(current)
        const dangling = danglingSchedules(current)
        return <Stack>
          <Alert>{t('operate.jobs.on')}</Alert>
          {queues.length > 0 && <Alert tone="warning">{t('operate.jobs.unserved', { names: queues.join(', ') })}</Alert>}
          {dangling.length > 0 && <Alert tone="warning">{t('operate.jobs.dangling', { names: dangling.join(', ') })}</Alert>}
        </Stack>
      }}
    </VersionedSettings>
  </Stack>
}
