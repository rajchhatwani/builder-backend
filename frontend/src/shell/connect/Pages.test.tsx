import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { validateValue, type JsonSchema } from '../../forms'
import { JobsPage } from '../operate/JobsPage'
import { WorkersPage } from '../operate/WorkersPage'
import { WorkflowsPage } from '../operate/WorkflowsPage'
import { ProvidersPage } from './ProvidersPage'
import { WebhooksPage } from './WebhooksPage'

const m = vi.hoisted(() => ({ getSpecBlocks: vi.fn(), validateProject: vi.fn() }))
vi.mock('../../api/client', () => ({ api: m }))
vi.mock('../../components/Ui', () => ({ useUi: () => ({ confirm: vi.fn(), toast: vi.fn() }) }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
async function mount(el: ReturnType<typeof createElement>) {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => { root!.render(el) })
  await act(async () => { await Promise.resolve() })
}
const q = (id: string) => host.querySelector(`[data-testid=${id}]`)
afterEach(() => { act(() => root?.unmount()); host?.remove(); root = null; Object.values(m).forEach((f) => f.mockReset()) })

const SPEC = {
  jobs: {
    enabled: true,
    worker_groups: [{ name: 'main', queues: ['default'], concurrency: 4, placement: 'separate_server' }],
    jobs: [{ name: 'send_mail', handler: 'send_mail', queue: 'mail', retry: { max_attempts: 5, backoff_seconds: 10, backoff: 'exponential' } }],
    schedules: [{ name: 'nightly', job: 'send_mail', cron: '0 2 * * *', timezone: 'Europe/Paris' }],
  },
  workflows: { enabled: true, workflows: [{ name: 'onboarding', roles: ['admin'], steps: [{ name: 'create', kind: 'hook' }, { name: 'mail', kind: 'job', job: 'missing' }] }] },
  providers: { enabled: true, adapters: [{ kind: 'email', name: 'smtp', settings: { host: 'mail.example.com', api_key: 'sk_live_SHOULD_NOT_SHOW' } }] },
  webhooks: { enabled: true, events: ['order.created'], inbound: [{ name: 'stripe' }] },
}

describe('spec-reading pages', () => {
  it('Jobs: tables, ReadOnly notice, validator issues', async () => {
    m.getSpecBlocks.mockResolvedValue(SPEC)
    m.validateProject.mockResolvedValue({ valid: false, issues: [{ path: 'jobs.jobs[0]', code: 'x', message: 'handler missing' }, { path: 'entities', code: 'y', message: 'other' }] })
    await mount(createElement(JobsPage, { projectId: 'p' }))
    expect(host.querySelector('h1')?.textContent).toBe('Jobs and schedules')
    expect(q('readonly-notice')).not.toBeNull()
    expect(q('jobs-table')?.textContent).toContain('send_mail')
    expect(q('sched-table')?.textContent).toContain('Europe/Paris')
    expect(q('block-issues')?.textContent).toContain('handler missing')
    expect(q('block-issues')?.textContent).not.toContain('other')
  })

  it('Jobs: off state when the block is missing', async () => {
    m.getSpecBlocks.mockResolvedValue({})
    m.validateProject.mockResolvedValue({ valid: true, issues: [] })
    await mount(createElement(JobsPage, { projectId: 'p' }))
    expect(q('block-off')).not.toBeNull()
  })

  it('shows a retryable error when the spec cannot be loaded', async () => {
    m.getSpecBlocks.mockRejectedValueOnce(new Error('offline')).mockResolvedValue(SPEC)
    m.validateProject.mockResolvedValue({ valid: true, issues: [] })
    await mount(createElement(JobsPage, { projectId: 'p' }))
    expect(q('block-error')?.textContent).toContain('offline')
    await act(async () => { host.querySelector<HTMLButtonElement>('[data-testid=block-error] button')!.click() })
    expect(q('jobs-table')).not.toBeNull()
  })

  it('Workers: placement, unserved queue warning, queue advisor note', async () => {
    m.getSpecBlocks.mockResolvedValue(SPEC)
    m.validateProject.mockResolvedValue({ valid: true, issues: [] })
    await mount(createElement(WorkersPage, { projectId: 'p' }))
    expect(q('workers-table')?.textContent).toContain('Separate server')
    expect(q('workers-unserved')?.textContent).toContain('mail')
    expect(q('queue-advisor')?.textContent).toContain('no builder endpoint yet')
  })

  it('Workflows: steps and a job step that names an undeclared job', async () => {
    m.getSpecBlocks.mockResolvedValue(SPEC)
    m.validateProject.mockResolvedValue({ valid: true, issues: [] })
    await mount(createElement(WorkflowsPage, { projectId: 'p' }))
    expect(q('wf-card')?.textContent).toContain('onboarding')
    expect(host.querySelectorAll('ol li')).toHaveLength(2)
    expect(q('wf-problems')?.textContent).toContain('"missing" is not declared')
  })

  it('Providers: never prints a secret-looking setting', async () => {
    m.getSpecBlocks.mockResolvedValue(SPEC)
    m.validateProject.mockResolvedValue({ valid: true, issues: [] })
    await mount(createElement(ProvidersPage, { projectId: 'p' }))
    expect(q('pv-table')?.textContent).toContain('mail.example.com')
    expect(host.textContent).not.toContain('SHOULD_NOT_SHOW')
  })

  it('Webhooks: spec summary, and says so when no preview API is configured', async () => {
    m.getSpecBlocks.mockResolvedValue(SPEC)
    m.validateProject.mockResolvedValue({ valid: true, issues: [] })
    await mount(createElement(WebhooksPage, { projectId: 'p', origin: null }))
    expect(q('wh-events')?.textContent).toContain('order.created')
    expect(q('wh-inbound')?.textContent).toContain('/webhooks/in/stripe')
    expect(q('wh-no-origin')).not.toBeNull()
    expect(q('wh-live')).toBeNull()
  })

  it('Webhooks: the live panel appears when a preview origin exists', async () => {
    m.getSpecBlocks.mockResolvedValue(SPEC)
    m.validateProject.mockResolvedValue({ valid: true, issues: [] })
    await mount(createElement(WebhooksPage, { projectId: 'p', origin: 'http://localhost:9999' }))
    expect(q('wh-live')).not.toBeNull()
    expect(host.querySelector<HTMLInputElement>('#wh-token')?.type).toBe('password')
  })
})

describe('validateValue with an unset optional object', () => {
  it('does not demand the required children of a null nullable object', () => {
    const schema = {
      type: 'object', required: [],
      properties: { thing: { anyOf: [{ $ref: '#/$defs/T' }, { type: 'null' }], default: null } },
      $defs: { T: { type: 'object', required: ['a'], properties: { a: { type: 'string' } } } },
    } as unknown as JsonSchema
    expect(validateValue(schema, schema, { thing: null })).toEqual({})
    expect(validateValue(schema, schema, { thing: {} })['thing.a']).toBeDefined()
  })
})
