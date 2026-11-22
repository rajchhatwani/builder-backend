import axe from 'axe-core'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import type { JsonSchema } from '../../forms'
import { resolve } from '../../forms/schemaLogic'
import gateway from '../../forms/schemas/ai-gateway.json'
import documents from '../../forms/schemas/ai-documents.json'
import knowledge from '../../forms/schemas/ai-knowledge.json'
import agents from '../../forms/schemas/ai-agents.json'
import evals from '../../forms/schemas/ai-evals.json'
import { AgentsSettingsPage, AiDocumentsSettingsPage, AiGatewaySettingsPage, EvalsSettingsPage, KnowledgeSettingsPage } from './AiSettingsPages'

const m = vi.hoisted(() => ({ getBlock: vi.fn(), putBlock: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({ ...(await orig<typeof import('../../api/client')>()), api: m }))
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
afterEach(() => { act(() => root?.unmount()); host?.remove(); root = null; Object.values(m).forEach((f) => f.mockReset()) })
const btn = (re: RegExp) => [...host.querySelectorAll('button')].find((b) => re.test(b.textContent ?? ''))!
const type = async (el: HTMLInputElement, v: string) => {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(el, v)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
const field = (path: string) => host.querySelector<HTMLInputElement>(`[data-field-path="${path}"] input, [data-field-path="${path}"] select`)!

const GATEWAY = { providers: [{ name: 'main', kind: 'fake', byo_key_env: null }], region: 'eu', zero_retention: false, stages: [{ name: 'answer', provider: 'main', model: 'm1', max_output_tokens: 512, fallback_model: null }], budget: { period: 'day', limit_micro_usd: 1000000, per_call_cap_micro_usd: 100000 }, roles: { call_roles: [], read_roles: ['admin'], manage_roles: ['admin'] } }
const DOCS = { kinds: [{ name: 'invoice', fields: [{ name: 'total', required: true }] }], stage: 'extract', upload_roles: [], review_roles: ['admin'], read_roles: [], review_below_bp: 8000, max_text_chars: 200000, allow_self_review: false }
const KNOW = { stage: 'answer', manage_roles: ['admin'], read_roles: [], chunk_chars: 800, max_sources: 1000, max_text_chars: 500000 }
const AGENTS = { actions: [{ name: 'note', kind: 'note', description: 'd', risk: 'low', max_autonomy: 'draft', entity: null, fields: ['a', 'b'] }], agents: [{ name: 'helper', stage: 'answer', actions: ['note'], autonomy: 'suggest', max_actions_per_run: 5, require_eval: null }], roles: { run_roles: [], approve_roles: ['admin'], read_roles: [] }, allow_self_approval: false }
const EVALS = { suites: [{ name: 's', agent: 'helper', pass_bp: 8000, cases: [{ name: 'c', goal: 'g', expect_actions: ['note'], forbid_actions: [] }] }], run_roles: ['admin'] }
const OTHER = { money: { ledger: { read_roles: ['admin'] } }, operations: { geo: { provider: 'fake' } } }

const PAGES = [
  { block: 'gateway', Page: AiGatewaySettingsPage, h1: 'AI gateway settings', schema: gateway, val: GATEWAY, focus: 'region', set: 'us', check: (b: any) => b.region === 'us' },
  { block: 'documents', Page: AiDocumentsSettingsPage, h1: 'AI documents settings', schema: documents, val: DOCS, focus: 'review_below_bp', set: '7000', check: (b: any) => b.review_below_bp === 7000 && b.kinds[0].fields[0].required === true },
  { block: 'knowledge', Page: KnowledgeSettingsPage, h1: 'Knowledge settings', schema: knowledge, val: KNOW, focus: 'chunk_chars', set: '500', check: (b: any) => b.chunk_chars === 500 },
  { block: 'agents', Page: AgentsSettingsPage, h1: 'AI agents settings', schema: agents, val: AGENTS, focus: 'agents.0.max_actions_per_run', set: '2', check: (b: any) => b.agents[0].max_actions_per_run === 2 && b.actions[0].fields.join() === 'a,b' },
  { block: 'evals', Page: EvalsSettingsPage, h1: 'AI evals settings', schema: evals, val: EVALS, focus: 'suites.0.pass_bp', set: '9000', check: (b: any) => b.suites[0].pass_bp === 9000 && b.suites[0].cases[0].expect_actions[0] === 'note' },
]

/** Every declared property (recursively, through list rows) must have a rendered field: nothing is silently dropped. */
function expectedPaths(root: JsonSchema, schema: JsonSchema, value: unknown, path: string[] = []): string[] {
  const s = resolve(root, schema)
  const out: string[] = []
  if (s.type === 'object' && s.properties) {
    const obj = (value ?? {}) as Record<string, unknown>
    for (const [k, p] of Object.entries(s.properties)) {
      out.push([...path, k].join('.'))
      out.push(...expectedPaths(root, p, obj[k], [...path, k]))
    }
  } else if (s.type === 'array' && s.items && (schema['x-ui'] ?? s['x-ui'])?.widget !== 'csv') {
    ;((value as unknown[]) ?? []).forEach((it, i) => out.push(...expectedPaths(root, s.items!, it, [...path, String(i)])))
  }
  return out
}

describe.each(PAGES)('$block settings page', ({ block, Page, h1, schema, val, focus, set, check }) => {
  // The other four AI blocks, as stored, must survive untouched.
  const AI = { gateway: GATEWAY, documents: DOCS, knowledge: KNOW, agents: AGENTS, evals: EVALS } as Record<string, unknown>
  const PACKS = { ...OTHER, ai: AI }

  it('renders one h1 and shows every field of the block', async () => {
    m.getBlock.mockResolvedValue({ packs: PACKS, version: 3 })
    await mount(createElement(Page, { projectId: 'p' }))
    expect(host.querySelectorAll('h1')).toHaveLength(1)
    expect(host.querySelector('h1')?.textContent).toBe(h1)
    expect(m.getBlock).toHaveBeenCalledWith('p', 'packs')
    const missing = expectedPaths(schema as JsonSchema, schema as JsonSchema, val).filter((p) => !host.querySelector(`[data-field-path="${p}"]`))
    expect(expectedPaths(schema as JsonSchema, schema as JsonSchema, val).length).toBeGreaterThanOrEqual(6)
    expect(missing).toEqual([])
  })

  it('saves, changing only this block', async () => {
    m.getBlock.mockResolvedValue({ packs: PACKS, version: 3 })
    m.putBlock.mockImplementation(async (_p: string, _n: string, b: { packs: unknown }) => ({ packs: b.packs, version: 4 }))
    await mount(createElement(Page, { projectId: 'p' }))
    await type(field(focus), set)
    await act(async () => { btn(/^Save$/).click() })
    expect(m.putBlock).toHaveBeenCalledTimes(1)
    const [pid, name, body] = m.putBlock.mock.calls[0]
    expect([pid, name, body.expected_version]).toEqual(['p', 'packs', 3])
    expect(check(body.packs.ai[block])).toBe(true)
    for (const k of Object.keys(AI).filter((k) => k !== block)) expect(body.packs.ai[k]).toEqual(AI[k])
    expect(body.packs.money).toEqual(OTHER.money)
    expect(body.packs.operations).toEqual(OTHER.operations)
    expect(host.querySelector('[data-testid=save-note]')?.textContent).toContain('version 4')
  })

  it('shows a 409 as a stale banner and a 422 next to the form', async () => {
    m.getBlock.mockResolvedValue({ packs: PACKS, version: 3 })
    m.putBlock.mockRejectedValueOnce(new ApiError(409, { code: 'conflict', message: 'stale', details: [] }))
    await mount(createElement(Page, { projectId: 'p' }))
    await type(field(focus), set)
    await act(async () => { btn(/^Save$/).click() })
    expect(host.querySelector('[data-testid=conflict]')).not.toBeNull()
    m.putBlock.mockRejectedValueOnce(new ApiError(422, { code: 'validation_error', message: 'Invalid spec', details: [{ loc: ['body', 'packs', 'ai', block, ...focus.split('.')], msg: 'bad value' }] }))
    await act(async () => { btn(/^Reload$/).click() })
    await type(field(focus), set)
    await act(async () => { btn(/^Save$/).click() })
    expect(host.textContent).toContain('bad value')
  })

  it('offers to switch the block on when the spec has none, with the schema defaults', async () => {
    m.getBlock.mockResolvedValue({ packs: { ai: {} }, version: 1 })
    m.putBlock.mockImplementation(async (_p: string, _n: string, b: { packs: unknown }) => ({ packs: b.packs, version: 2 }))
    await mount(createElement(Page, { projectId: 'p' }))
    expect(host.querySelector('[data-testid=block-off]')).not.toBeNull()
    await act(async () => { btn(/^Switch on/).click() })
    expect(m.putBlock.mock.calls[0][2].packs.ai[block]).toBeDefined()
  })

  it('has no axe violations', async () => {
    m.getBlock.mockResolvedValue({ packs: PACKS, version: 3 })
    await mount(createElement(Page, { projectId: 'p' }))
    const res = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' ')}`)).toEqual([])
  })
})
