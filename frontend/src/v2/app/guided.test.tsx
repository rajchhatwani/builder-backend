// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { App } from './App'
import { createAppRouter } from './router'

const project = '95ff34eb-4d07-4a60-8669-aaf1cf5442ca'
const run = '650a3687-da30-4199-8a69-ea345337918d'
const approval = {
  id: '98a826dd-0002-4ed3-9d0b-359875fec600', run_id: run, kind: 'A', subject: 'Approve time-off plan',
  payload: { plan: { entities: ['Employee', 'TimeOff'] } }, risk_flags: [], requires_owner: false,
  state: 'pending', payload_hash: 'reviewed-payload', bound_spec_hash: 'reviewed-spec', bound_commit: 'reviewed-commit',
  expires_at: '2099-01-01T00:00:00Z', created_at: '2026-01-01T00:00:00Z', decision_note: null,
}
const requirements = {
  id: 'map', status: 'needs_answers',
  items: [{ id: 'item', kind: 'entity', text: '<strong>Employee</strong>', source_doc: 'brief.pdf', source_page: 2, status: 'covered' }],
  questions: [{ id: 'q', text: 'Who approves leave?', assumption: 'A manager', state: 'open' }],
  coverage: { total: 1, open: 0, covered: 1, out_of_scope: 0, percent_covered: 100, open_questions: 1 },
  phases: [{ number: 2, name: 'Behaviour', items: 1 }], sources: [],
}

function open(section: string, handler: (path: string, init?: RequestInit) => unknown, role = 'editor') {
  const fetch = vi.fn((url: string, init?: RequestInit) => {
    const { pathname } = new URL(url)
    const path = pathname.replace(`/projects/${project}`, '')
    const result = path === '/account/me' ? { id: 'user', email_verified_at: '2026-01-01', platform_role: 'customer' }
      : path === '/members' ? [{ user_id: 'user', role }] : path === '/workspaces' ? []
      : path === '/status' ? { sections: [] } : handler(path, init)
    return Promise.resolve(result instanceof Response ? result : Response.json(result ?? {}, { status: result == null ? 500 : 200 }))
  })
  vi.stubGlobal('fetch', fetch)
  const client = new QueryClient()
  const router = createAppRouter(client, createMemoryHistory({ initialEntries: [`/projects/${project}/${section}`] }))
  render(<App queryClient={client} router={router} />)
  return { fetch, router }
}

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it('renders requirements as plain text and binds a confirmed start to the selected phase', async () => {
  const { fetch, router } = open('intake?phase=2', path => path === '/requirements/start-run' ? { id: run } : requirements)
  expect(await screen.findByText('<strong>Employee</strong>')).toBeTruthy()
  expect(screen.getByText('From brief.pdf, page 2')).toBeTruthy()
  expect(screen.getByTestId('coverage-summary').textContent).toContain('1 of 1')
  fireEvent.click(await screen.findByTestId('start-build'))
  expect(fetch.mock.calls.some(([url]) => url.endsWith('/start-run'))).toBe(false)
  const dialog = await screen.findByRole('dialog', { name: 'Confirm assumptions' })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Accept assumptions and start' }))
  await waitFor(() => expect(router.state.location.pathname).toBe(`/projects/${project}/build`))
  expect(router.state.location.search.run).toBe(run)
  const start = fetch.mock.calls.find(([url]) => url.endsWith('/start-run'))
  expect(JSON.parse(String(start?.[1]?.body))).toEqual({ accept_assumptions: true, phase: 2, workspace_id: null })
})

it('keeps the intake draft after cancelling guided navigation', async () => {
  const { router } = open('intake', path => path === '/requirements' ? requirements : [])
  const input = await screen.findByRole('textbox', { name: 'What should the backend do?' }) as HTMLTextAreaElement
  await waitFor(() => expect(input.disabled).toBe(false))
  fireEvent.change(input, { target: { value: 'Keep this draft' } })
  fireEvent.click(screen.getByRole('link', { name: 'Review plan' }))
  const dialog = await screen.findByRole('dialog', { name: 'Leave without saving your request?' })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
  expect(router.state.location.pathname).toBe(`/projects/${project}/intake`)
  expect(input.value).toBe('Keep this draft')
})

it('reads through a failed intake and leaves the draft available for retry', async () => {
  let submitted = false
  open('intake', path => {
    if (path === '/requirements/intake') {
      submitted = true
      return Response.json({ code: 'provider_error', message: 'Document processing stopped', details: [] }, { status: 502 })
    }
    if (path === '/requirements') return submitted ? requirements
      : { id: null, status: 'empty', sources: [], questions: [], items: [] }
  })
  const input = await screen.findByRole('textbox', { name: 'What should the backend do?' }) as HTMLTextAreaElement
  await waitFor(() => expect(input.disabled).toBe(false))
  fireEvent.change(input, { target: { value: 'Keep this draft' } })
  fireEvent.click(screen.getByTestId('intake-submit'))
  expect(await screen.findByText('<strong>Employee</strong>')).toBeTruthy()
  expect(await screen.findByText('Document processing stopped')).toBeTruthy()
  expect(input.value).toBe('Keep this draft')
})

it('blocks a stale plan decision when the bound commit has changed', async () => {
  const { fetch } = open(`plan?run=${run}`, path => path === '/agent/approvals' ? [approval]
    : { ...approval, bound_commit: 'new-commit', payload: { plan: { entities: ['Department'] } } })
  fireEvent.click(await screen.findByTestId('plan-approve'))
  expect(await screen.findByTestId('plan-changed')).toBeTruthy()
  expect(screen.getByText('Department')).toBeTruthy()
  expect(fetch.mock.calls.some(([url]) => url.endsWith('/decision'))).toBe(false)
})

it('sends the approved edited scope and the original reviewed bindings', async () => {
  const { fetch } = open(`plan?run=${run}`, path => path === '/agent/approvals' ? [approval] : path.endsWith('/decision')
    ? { ...approval, state: 'approved', payload_hash: 'new', payload: { plan: { entities: ['Employee'] }, edited_from: approval.payload.plan, edited_by: 'user' } }
    : approval)
  fireEvent.click(await screen.findByRole('button', { name: /Remove TimeOff/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Approve my edited plan' }))
  expect(await screen.findByTestId('plan-edited-from')).toBeTruthy()
  const decision = fetch.mock.calls.find(([url]) => url.endsWith('/decision'))
  expect(JSON.parse(String(decision?.[1]?.body))).toEqual({
    approve: true, plan: { entities: ['Employee'] }, expected_payload_hash: 'reviewed-payload', expected_spec_hash: 'reviewed-spec',
  })
})

it('shows an owner-only extension read-only to editors', async () => {
  open('plan', () => [{ ...approval, requires_owner: true, payload: { extend_items: [{ kind: 'hook', name: 'audit' }] } }])
  expect(await screen.findByText('audit')).toBeTruthy()
  expect(await screen.findByTestId('plan-gate-reason')).toBeTruthy()
  expect(screen.queryByTestId('plan-approve')).toBeNull()
  expect(screen.queryByRole('textbox', { name: 'Name to add' })).toBeNull()
})

it('requires a denial note before confirmation and sends no edited scope', async () => {
  const { fetch } = open(`plan?run=${run}`, path => path === '/agent/approvals' ? [approval] : path.endsWith('/decision')
    ? { ...approval, state: 'denied', decision_note: 'Include the backup approver' } : approval)
  fireEvent.click(await screen.findByTestId('plan-deny'))
  const note = screen.getByRole('textbox', { name: 'Note (required to deny)' })
  expect(await screen.findByText('Write a note to deny the plan, so the agent knows what to change.')).toBeTruthy()
  expect(document.activeElement).toBe(note)
  fireEvent.change(note, { target: { value: 'Include the backup approver' } })
  fireEvent.click(screen.getByTestId('plan-deny'))
  const dialog = await screen.findByRole('dialog', { name: 'Deny this plan?' })
  expect(fetch.mock.calls.some(([url]) => url.endsWith('/decision'))).toBe(false)
  fireEvent.click(within(dialog).getByRole('button', { name: 'Deny' }))
  expect(await screen.findByTestId('plan-done')).toBeTruthy()
  const decision = fetch.mock.calls.find(([url]) => url.endsWith('/decision'))
  expect(JSON.parse(String(decision?.[1]?.body))).toEqual({
    approve: false, note: 'Include the backup approver', expected_payload_hash: 'reviewed-payload', expected_spec_hash: 'reviewed-spec',
  })
})
