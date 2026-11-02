import type { JsonSchema } from '../../forms'
import schema from '../../forms/schemas/jobs.json'
import { BlockFormPage } from '../connect/BlockFormPage'
import { danglingSchedules, unservedQueues } from '../connect/blockLogic'
import type { SpecJobs } from '../connect/specTypes'

/** Operate > Jobs and schedules: job kinds, retries, worker groups and cron schedules, editable through PUT /behavior/jobs. */
export function JobsPage({ projectId }: { projectId: string }) {
  return (
    <BlockFormPage projectId={projectId} path="jobs" key_="jobs" title="Jobs and schedules" schema={schema as JsonSchema}
      intro="Background work your project runs: job kinds with retries, worker groups, and schedules that start them on a cron."
      status={(c) => {
        const j = c as SpecJobs
        const dangling = danglingSchedules(j)
        const unserved = unservedQueues(j)
        return (
          <>
            Background jobs are <strong>{j.enabled ? 'switched on' : 'switched off'}</strong>.
            {dangling.length > 0 && <span role="alert" data-testid="jobs-dangling"> Schedules that point at a job that is not declared: {dangling.join(', ')}.</span>}
            {unserved.length > 0 && <span data-testid="jobs-unserved"> No worker group serves: {unserved.join(', ')}.</span>}
          </>
        )
      }} />
  )
}
