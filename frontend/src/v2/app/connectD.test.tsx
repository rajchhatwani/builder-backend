// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { members, projectId, root, user } from '../../../e2e/v2/fixtures/connect-a'
import { packRoles, packsReply } from '../../../e2e/v2/fixtures/connect-c'
import { advancedPacks, advancedPackSpec, advancedScreens } from '../../../e2e/v2/fixtures/connect-d'
import { entryKeys } from '../features/entry/api/entry'
import { App } from './App'
import { createAppRouter } from './router'

const path = root + '/behavior/packs'
type Write = { packs: typeof advancedPacks; expected_version: number }
function open(section: string, respond?: (method: string, body: Write) => Response | undefined, fixture: unknown = advancedPacks) {
  let current = structuredClone(fixture)
  let version = 3
  const writes: Write[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
    const { pathname } = new URL(url, window.location.origin)
    if (pathname === '/account/me') return Response.json(user)
    if (pathname === '/orgs') return Response.json({ items: [], total: 0 })
    if (pathname === root) return Response.json({ id: projectId, name: 'People Directory', slug: 'directory', version: 1 })
    if (pathname === root + '/status') return Response.json({ ready: true, sections: [], issues: [], counts: {} })
    if (pathname === root + '/members') return Response.json(members)
    if (pathname === root + '/workspaces' || pathname === root + '/previews') return Response.json([])
    if (pathname === root + '/spec') return Response.json(advancedPackSpec)
    if (pathname === root + '/behavior/roles') return Response.json({ roles: packRoles })
    if (pathname === root + '/behavior/issues') return Response.json({ issues: [] })
    if (pathname === path) {
      if (options?.method !== 'PUT') return Response.json(packsReply(current, version))
      const body = JSON.parse(String(options.body)) as Write
      writes.push(body)
      const response = respond?.('PUT', body)
      if (response) return response
      current = body.packs
      return Response.json(packsReply(current, ++version))
    }
    return Response.json({ code: 'not_found', details: [] }, { status: 404 })
  }))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(entryKeys.session(), user)
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [root + '/' + section] }))
  render(<App router={router} queryClient={queryClient} />)
  return writes
}

beforeEach(() => {
  localStorage.setItem('v2-language', 'en')
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})
afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals() })

async function mainFor(id: keyof typeof advancedScreens) {
  const main = within(await screen.findByRole('main'))
  await main.findByRole('heading', { name: advancedScreens[id].title }, { timeout: 5000 })
  await waitFor(() => expect(main.getByTestId('switch-off').querySelector('button')).toHaveProperty('disabled', false))
  return main
}

const screens = [
  ['matchingsettings', 'Max load', '20', { operations: { matching: { max_load: 20 } } }],
  ['predictionsettings', 'Interval bp', '2500', { operations: { prediction: { interval_bp: 2500 } } }],
  ['aigatewaysettings', 'Limit micro USD', '2000000', { ai: { gateway: { budget: { limit_micro_usd: 2000000 } } } }],
  ['aidocssettings', 'Review below bp', '7500', { ai: { documents: { review_below_bp: 7500 } } }],
  ['knowledgesettings', 'Chunk chars', '900', { ai: { knowledge: { chunk_chars: 900 } } }],
  ['agentssettings', 'Max actions per run', '7', { ai: { agents: { agents: [{ max_actions_per_run: 7 }] } } }],
  ['evalssettings', 'Pass bp', '9000', { ai: { evals: { suites: [{ pass_bp: 9000 }] } } }],
] as const

it.each(screens)('%s saves its own fields through the packs endpoint', async (id, label, value, expected) => {
  const writes = open(id)
  const main = await mainFor(id)
  fireEvent.change(main.getByRole('spinbutton', { name: label }), { target: { value } })
  fireEvent.click(main.getByRole('button', { name: /^Save$/ }))
  await waitFor(() => expect(main.getByTestId('save-note').textContent).toBe('Saved (version 4).'))
  expect(writes).toMatchObject([{ expected_version: 3, packs: { money: advancedPacks.money, booking: advancedPacks.booking, ...expected } }])
  const [pack, block] = advancedScreens[id].path
  for (const key of ['operations', 'ai'] as const) {
    const saved = writes[0].packs[key]
    for (const [sibling, initial] of Object.entries(advancedPacks[key])) {
      if (key !== pack || sibling !== block) expect(saved[sibling as keyof typeof saved]).toEqual(initial)
    }
  }
})

it('maps a nested 422 to the eval case and preserves its draft', async () => {
  open('evalssettings', () => Response.json({
    code: 'invalid_spec', message: 'Could not save the case.',
    details: [{ loc: ['body', 'packs', 'ai', 'evals', 'suites', 0, 'cases', 0, 'goal'], msg: 'Goal was rejected.' }],
  }, { status: 422 }))
  const main = await mainFor('evalssettings')
  const goal = main.getByRole('textbox', { name: 'Goal' })
  fireEvent.change(goal, { target: { value: 'Check the draft.' } })
  fireEvent.click(main.getByRole('button', { name: /^Save$/ }))
  expect(await main.findByText('Goal was rejected.')).toBeTruthy()
  expect(goal).toHaveProperty('value', 'Check the draft.')
})

it('switches on the gateway with backend defaults and keeps the other AI blocks', async () => {
  const writes = open('aigatewaysettings', undefined, { ...advancedPacks, ai: { ...advancedPacks.ai, gateway: null } })
  const action = await screen.findByRole('button', { name: 'Switch on ai gateway settings' }, { timeout: 5000 })
  await waitFor(() => expect(action).toHaveProperty('disabled', false))
  fireEvent.click(action)
  const main = await mainFor('aigatewaysettings')
  await waitFor(() => expect(main.getByTestId('save-note').textContent).toBe('Saved (version 4).'))
  expect(writes).toEqual([{ expected_version: 3, packs: { ...advancedPacks, ai: { ...advancedPacks.ai, gateway: {
    region: 'eu', zero_retention: false, providers: [], stages: [],
    budget: { period: 'day', limit_micro_usd: 1000000, per_call_cap_micro_usd: 100000 },
    roles: { call_roles: [], read_roles: ['admin'], manage_roles: ['admin'] },
  } } } }])
})

it('adds and reorders document fields before saving and confirms removal', async () => {
  const writes = open('aidocssettings')
  const main = await mainFor('aidocssettings')
  fireEvent.click(main.getByRole('button', { name: 'Add field' }))
  const fields = within(main.getByRole('group', { name: 'Fields' }))
  const newField = within(fields.getByRole('group', { name: 'Field 2' }))
  fireEvent.change(newField.getByRole('textbox', { name: 'Name' }), { target: { value: 'currency' } })
  fireEvent.click(newField.getByRole('button', { name: 'Move Field 2 up' }))
  const oldField = within(fields.getByRole('group', { name: 'Field 2' }))
  expect(oldField.getByRole('textbox', { name: 'Name' })).toHaveProperty('value', 'total')
  fireEvent.click(oldField.getByRole('button', { name: 'Remove Field 2' }))
  const dialog = within(await screen.findByRole('dialog'))
  expect(fields.getByText('Field 2', { exact: true })).toBeTruthy()
  fireEvent.click(dialog.getByRole('button', { name: /^Remove$/ }))
  await waitFor(() => expect(fields.queryByRole('group', { name: 'Field 2' })).toBeNull())
  fireEvent.click(main.getByRole('button', { name: /^Save$/ }))
  await waitFor(() => expect(main.getByTestId('save-note').textContent).toBe('Saved (version 4).'))
  expect(writes[0].packs.ai.documents.kinds[0].fields).toEqual([{ name: 'currency', required: false }])
})

it('shows field bounds and preserves edits when the client blocks a save', async () => {
  const writes = open('matchingsettings')
  const main = await mainFor('matchingsettings')
  const load = main.getByRole('spinbutton', { name: 'Max load' })
  fireEvent.change(load, { target: { value: '0' } })
  fireEvent.blur(load)
  expect(await main.findByText('Max load must be a whole number from 1 to 1,000,000.')).toBeTruthy()
  fireEvent.click(main.getByRole('button', { name: /^Save$/ }))
  expect(writes).toHaveLength(0)
  expect(load).toHaveProperty('value', '0')
})
