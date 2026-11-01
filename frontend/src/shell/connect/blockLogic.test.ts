import { describe, expect, it } from 'vitest'
import { danglingSchedules, displaySetting, issuesFor, placementLabel, retrySummary, totalConcurrency, unservedQueues, urlPolicyText, workflowJobProblems } from './blockLogic'

const jobs = {
  enabled: true,
  worker_groups: [{ name: 'main', queues: ['default'], concurrency: 4 }, { name: 'mail', queues: ['mail'], concurrency: 2, placement: 'separate_server' }],
  jobs: [{ name: 'a', handler: 'a' }, { name: 'b', queue: 'mail', handler: 'b' }, { name: 'c', queue: 'slow', handler: 'c' }],
  schedules: [{ name: 's1', job: 'a', cron: '* * * * *' }, { name: 's2', job: 'ghost', cron: '0 * * * *' }],
}

describe('blockLogic', () => {
  it('filters issues by path prefix without matching look-alikes', () => {
    const issues = [{ path: 'jobs.jobs[0]', code: 'x', message: 'm1' }, { path: 'jobs', code: 'x', message: 'm2' }, { path: 'jobsx', code: 'x', message: 'm3' }, { path: 'webhooks', code: 'x', message: 'm4' }]
    expect(issuesFor(issues, 'jobs').map((i) => i.message)).toEqual(['m1', 'm2'])
    expect(issuesFor(null, 'jobs')).toEqual([])
  })
  it('finds queues no worker group serves and schedules without a job', () => {
    expect(unservedQueues(jobs)).toEqual(['slow'])
    expect(unservedQueues(null)).toEqual([])
    expect(danglingSchedules(jobs)).toEqual(['s2'])
    expect(totalConcurrency(jobs)).toBe(6)
  })
  it('labels placement and retries', () => {
    expect(placementLabel(undefined)).toMatch(/Same server/)
    expect(placementLabel('separate_server')).toMatch(/Separate server/)
    expect(placementLabel('mars')).toContain('mars')
    expect(retrySummary({ max_attempts: 1, backoff_seconds: 5, backoff: 'fixed' })).toBe('1 attempt, fixed wait from 5 s')
    expect(retrySummary(undefined)).toBe('default retries')
  })
  it('reports workflow steps that name an undeclared job', () => {
    const wf = { enabled: true, workflows: [{ name: 'w', steps: [{ name: 's1', kind: 'job', job: 'a' }, { name: 's2', kind: 'job', job: 'nope' }, { name: 's3', kind: 'job' }, { name: 's4' }] }] }
    expect(workflowJobProblems(wf, jobs)).toEqual(['w / s2: job "nope" is not declared', 'w / s3: no job named'])
  })
  it('describes the webhook URL policy', () => {
    expect(urlPolicyText(false, [])).toContain('https only')
    expect(urlPolicyText(true, [8443])).toContain('8443')
  })
  it('never shows a secret-looking adapter setting', () => {
    expect(displaySetting('region', 'eu')).toBe('eu')
    expect(displaySetting('api_key', 'sk_live_123')).not.toContain('sk_live_123')
    expect(displaySetting('clientSecret', 'zzz')).not.toContain('zzz')
  })
})
