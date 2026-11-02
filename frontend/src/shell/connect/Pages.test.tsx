import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { validateValue, type JsonSchema } from '../../forms'
import { JobsPage } from '../operate/JobsPage'
import { WorkersPage } from '../operate/WorkersPage'
import { WorkflowsPage } from '../operate/WorkflowsPage'
import { ApiError } from '../../api/client'
import { ProvidersPage } from './ProvidersPage'
import { WebhooksPage } from './WebhooksPage'

const m = vi.hoisted(() => ({ getSpecBlocks: vi.fn(), validateProject: vi.fn(), getBlock: vi.fn(), putBlock: vi.fn(), getAdvisor: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({ ...(await orig<typeof import('../../api/client')>()), api: m }))
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

const BLOCKS: Record<string, { key: string; path: string; Page: (p: { projectId: string }) => ReturnType<typeof createElement>; title: string }> = {
  jobs: { key: 'jobs', path: 'jobs', Page: (p) => createElement(JobsPage, p), title: 'Jobs and schedules' },
  workflows: { key: 'workflows', path: 'workflows', Page: (p) => createElement(WorkflowsPage, p), title: 'Workflows' },
  providers: { key: 'providers', path: 'providers', Page: (p) => createElement(ProvidersPage, p), title: 'Provider integrations' },
  webhooks: { key: 'webhooks', path: 'webhooks', Page: (p) => createElement(WebhooksPage, { ...p, origin: null }), title: 'Webhooks' },
}
const btn = (re: RegExp) => [...host.querySelectorAll('button')].find((b) => re.test(b.textContent ?? ''))!
describe.each(Object.keys(BLOCKS))('%s page (editable block)', (name) => {
  const { key, path, Page, title } = BLOCKS[name]
  const block = SPEC[key as keyof typeof SPEC]
  beforeEach(() => {
    m.getSpecBlocks.mockResolvedValue(SPEC)
    m.validateProject.mockResolvedValue({ valid: true, issues: [] })
    m.getBlock.mockResolvedValue({ [key]: block, version: 2 })
  })

  it('loads the block from its own endpoint into a form', async () => {
    await mount(Page({ projectId: 'p' }))
    expect(host.querySelector('h1')?.textContent).toBe(title)
    expect(m.getBlock).toHaveBeenCalledWith('p', path)
    expect(host.querySelector('[data-schema-form]')).not.toBeNull()
  })

  it('save success sends the block with the loaded version', async () => {
    m.putBlock.mockImplementation(async (_p: string, _n: string, b: Record<string, unknown>) => ({ [key]: b[key], version: 3 }))
    await mount(Page({ projectId: 'p' }))
    const toggle = host.querySelector<HTMLInputElement>('input[type=checkbox]')!
    await act(async () => { toggle.click() })
    await act(async () => { btn(/^Save$/).click() })
    expect(m.putBlock).toHaveBeenCalledTimes(1)
    const [pid, n, body] = m.putBlock.mock.calls[0]
    expect([pid, n]).toEqual(['p', path])
    expect(body.expected_version).toBe(2)
    expect(body[key]).toBeTypeOf('object')
    expect(body[key]).not.toHaveProperty('version')
    expect(host.querySelector('[data-testid=save-note]')?.textContent).toContain('version 3')
  })

  it('shows the backend 422 message', async () => {
    m.putBlock.mockRejectedValue(new ApiError(422, { code: 'secret_in_spec', message: 'a secret must not be stored in the spec', details: [] }))
    await mount(Page({ projectId: 'p' }))
    await act(async () => { host.querySelector<HTMLInputElement>('input[type=checkbox]')!.click() })
    await act(async () => { btn(/^Save$/).click() })
    expect(host.querySelector('[role=alert]')?.textContent).toContain('a secret must not be stored')
  })

  it('shows the conflict banner on 409 and reloads on request', async () => {
    m.putBlock.mockRejectedValue(new ApiError(409, { code: 'conflict', message: 'stale', details: [] }))
    await mount(Page({ projectId: 'p' }))
    await act(async () => { host.querySelector<HTMLInputElement>('input[type=checkbox]')!.click() })
    await act(async () => { btn(/^Save$/).click() })
    expect(q('conflict')).not.toBeNull()
    const calls = m.getBlock.mock.calls.length
    await act(async () => { host.querySelector<HTMLButtonElement>('[data-testid=conflict] button')!.click() })
    expect(m.getBlock.mock.calls.length).toBe(calls + 1)
  })

  it('shows a retryable load error', async () => {
    m.getBlock.mockReset()
    m.getBlock.mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ [key]: block, version: 2 })
    await mount(Page({ projectId: 'p' }))
    expect(host.querySelector('[role=alert]')?.textContent).toContain('offline')
    await act(async () => { btn(/Try again/).click() })
    expect(host.querySelector('[data-schema-form]')).not.toBeNull()
  })
})

describe('Webhooks live panel', () => {
  it('says so when no preview API is configured, and shows the panel when one exists', async () => {
    m.getSpecBlocks.mockResolvedValue(SPEC)
    m.validateProject.mockResolvedValue({ valid: true, issues: [] })
    m.getBlock.mockResolvedValue({ webhooks: SPEC.webhooks, version: 1 })
    await mount(createElement(WebhooksPage, { projectId: 'p', origin: null }))
    expect(q('wh-no-origin')).not.toBeNull()
    act(() => root?.unmount()); host.remove()
    await mount(createElement(WebhooksPage, { projectId: 'p', origin: 'http://localhost:9999' }))
    expect(q('wh-live')).not.toBeNull()
  })
})

describe('Workers page', () => {
  beforeEach(() => {
    m.getSpecBlocks.mockResolvedValue(SPEC)
    m.validateProject.mockResolvedValue({ valid: true, issues: [] })
  })
  it('placement, unserved queue warning and the advisor result', async () => {
    m.getAdvisor.mockResolvedValue({ queue: { recommended_backend: 'postgres', reason: 'low volume' }, workflow: { runtime: 'postgres' } })
    await mount(createElement(WorkersPage, { projectId: 'p' }))
    expect(q('workers-table')?.textContent).toContain('Separate server')
    expect(q('workers-unserved')?.textContent).toContain('mail')
    expect(q('advisor-queue')?.textContent).toContain('low volume')
    expect(q('advisor-workflow')?.textContent).toContain('postgres')
  })
  it('shows a retryable advisor error without hiding the page', async () => {
    m.getAdvisor.mockRejectedValueOnce(new Error('no advisor')).mockResolvedValue({ queue: {}, workflow: {} })
    await mount(createElement(WorkersPage, { projectId: 'p' }))
    expect(q('workers-table')).not.toBeNull()
    expect(q('advisor-error')?.textContent).toContain('no advisor')
    await act(async () => { host.querySelector<HTMLButtonElement>('[data-testid=advisor-error] button')!.click() })
    expect(q('advisor-queue')).not.toBeNull()
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

describe('providers page: free-form settings', () => {
  const area = () => host.querySelector<HTMLTextAreaElement>('textarea')!
  const edit = (v: string) => act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(area(), v)
    area().dispatchEvent(new Event('input', { bubbles: true }))
  })
  beforeEach(() => {
    m.getBlock.mockResolvedValue({ providers: { enabled: true, adapters: [{ kind: 'email', name: 'acme_mail', settings: { region: 'eu' } }] }, version: 1 })
  })
  it('shows settings as JSON (no [object Object]) and saves them back as an object', async () => {
    m.putBlock.mockImplementation(async (_p: string, _n: string, b: Record<string, unknown>) => ({ providers: b.providers, version: 2 }))
    await mount(createElement(ProvidersPage, { projectId: 'p' }))
    expect(area().value).toContain('"region": "eu"')
    expect(host.textContent).not.toContain('[object Object]')
    await edit('{"region": "us"}')
    await act(async () => { btn(/^Save$/).click() })
    const sent = m.putBlock.mock.calls[0][2] as { providers: { adapters: { settings: unknown }[] } }
    expect(sent.providers.adapters[0].settings).toEqual({ region: 'us' })
  })
  it('invalid JSON blocks Save', async () => {
    await mount(createElement(ProvidersPage, { projectId: 'p' }))
    await edit('{oops')
    await act(async () => { btn(/^Save$/).click() })
    expect(m.putBlock).not.toHaveBeenCalled()
    expect(host.textContent).toContain('Fix the JSON fields')
  })
})
