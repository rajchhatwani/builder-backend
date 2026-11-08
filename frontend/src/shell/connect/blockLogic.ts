import type { ValidationIssue } from '../../api/types'
import type { SpecJobs, SpecWorkflows } from './specTypes'

/** Backend validation issues whose path starts with one of the prefixes ("jobs", "jobs.jobs[0]"...). */
export function issuesFor(issues: ValidationIssue[] | null | undefined, ...prefixes: string[]): ValidationIssue[] {
  return (issues ?? []).filter((i) => prefixes.some((p) => i.path === p || i.path.startsWith(`${p}.`) || i.path.startsWith(`${p}[`)))
}

export const PLACEMENT_LABEL: Record<string, string> = {
  same_server: 'Same server as the API (one more compose service)',
  separate_server: 'Separate server (bundle under deploy/workers/<name>/)',
}
export const placementLabel = (p: string | undefined) => PLACEMENT_LABEL[p ?? 'same_server'] ?? `Unknown placement "${p}"`

/** Queues that jobs use but no worker group serves: those jobs would wait forever. Derived from the spec only. */
export function unservedQueues(jobs: SpecJobs | null | undefined): string[] {
  if (!jobs) return []
  const served = new Set((jobs.worker_groups ?? []).flatMap((g) => g.queues ?? ['default']))
  const used = new Set((jobs.jobs ?? []).map((j) => j.queue ?? 'default'))
  return [...used].filter((q) => !served.has(q)).sort()
}

/** Schedules pointing at a job that is not declared. */
export function danglingSchedules(jobs: SpecJobs | null | undefined): string[] {
  const names = new Set((jobs?.jobs ?? []).map((j) => j.name))
  return (jobs?.schedules ?? []).filter((s) => !names.has(s.job)).map((s) => s.name)
}

/** Total job slots the worker groups can run at once, per process. */
export const totalConcurrency = (jobs: SpecJobs | null | undefined) =>
  (jobs?.worker_groups ?? []).reduce((n, g) => n + (g.concurrency ?? 4), 0)

export function retrySummary(r: { max_attempts?: number; backoff_seconds?: number; backoff?: string } | undefined): string {
  if (!r) return 'default retries'
  const n = r.max_attempts ?? 3
  const wait = r.backoff_seconds ?? 30
  return `${n} ${n === 1 ? 'attempt' : 'attempts'}, ${r.backoff === 'fixed' ? 'fixed' : 'doubling'} wait from ${wait} s`
}

/** Workflow steps that reference a job that is not declared (kind "job"). */
export function workflowJobProblems(workflows: SpecWorkflows | null | undefined, jobs: SpecJobs | null | undefined): string[] {
  const names = new Set((jobs?.jobs ?? []).map((j) => j.name))
  const out: string[] = []
  for (const w of workflows?.workflows ?? []) {
    for (const s of w.steps ?? []) {
      if (s.kind === 'job' && (!s.job || !names.has(s.job))) out.push(`${w.name} / ${s.name}: ${s.job ? `job "${s.job}" is not declared` : 'no job named'}`)
    }
  }
  return out
}

/** A hostname-free summary of where webhooks may go, for the page header. */
export function urlPolicyText(allowHttp: boolean | undefined, ports: number[] | undefined): string {
  const scheme = allowHttp ? 'http and https (http is meant for local testing only)' : 'https only'
  const p = ports?.length ? `, ports ${ports.join(', ')} besides 443` : ', port 443 only'
  return `${scheme}${p}; public addresses only, redirects are not followed`
}

/** A signing secret shown once is cleared from the page after this long, even if nobody dismissed it. */
export const MAX_SECRET_SHOWN_MS = 5 * 60_000

const SECRETISH = /(secret|token|password|passwd|api[_-]?key|private[_-]?key|credential)/i
/** Adapter settings are non-secret by contract (validation reports `secret_in_spec`). If one still looks like a
 *  secret, the page shows only that it exists, never the value. */
export function displaySetting(key: string, value: string | number | boolean): string {
  return SECRETISH.test(key) ? '(hidden: looks like a secret, remove it from the spec)' : String(value)
}
