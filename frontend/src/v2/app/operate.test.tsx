// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { members, projectId, root, time, user } from '../../../e2e/v2/fixtures/connect-a'
import { advisor, hits, jobSettings, metric, metricValue, observation, operateSpec, report, reportRun, workflowSettings } from '../../../e2e/v2/fixtures/operate-a'
import { entryKeys } from '../features/entry/api/entry'
import { App } from './App'
import { createAppRouter } from './router'

const index = { indexed: 1, index: 'database', entities: [{ entity: 'Invoice', searchable_fields: 1, records: 1 }] }
const addresses: Record<string, unknown> = {
  '/orgs': { items: [], total: 0 },
  [root]: { id: projectId, name: 'Billing workspace', version: 3 },
  [root + '/status']: { ready: true, sections: [], counts: {}, issues: [] },
  [root + '/members']: members,
  [root + '/previews']: [],
  [root + '/workspaces']: [],
  [root + '/spec']: operateSpec,
  [root + '/behavior/issues']: { issues: [] },
  [root + '/behavior/roles']: { roles: [{ name: 'employee', label: 'Employee' }] },
  [root + '/observability']: observation,
  [root + '/observability/issues']: { issues: [] },
  [root + '/behavior/jobs']: { jobs: jobSettings, version: 3, updated_at: time },
  [root + '/behavior/workflows']: { workflows: workflowSettings, version: 3, updated_at: time },
  [root + '/advisor']: advisor,
  [root + '/metrics']: { items: [metric], total: 1 },
  [root + '/metrics/' + metric.key + '/value']: metricValue,
  [root + '/reports']: { items: [report], total: 1 },
  [root + '/reports/' + report.id + '/value']: { report_id: report.id, computed_at: time, values: reportRun.values },
  [root + '/reports/' + report.id + '/runs']: { items: [reportRun], total: 1, limit: 20, offset: 0 },
  [root + '/search']: hits,
  [root + '/search/reindex']: index,
}

function open(path: string, override?: (url: URL, init?: RequestInit) => Response | undefined) {
  const fetcher = vi.fn(async (value: string, init?: RequestInit) => {
    const url = new URL(value)
    return override?.(url, init) ?? (Object.hasOwn(addresses, url.pathname) ?
      Response.json(addresses[url.pathname]) : Response.json({ code: 'not_found', details: [] }, { status: 404 }))
  })
  vi.stubGlobal('fetch', fetcher)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(entryKeys.session(), user)
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [root + '/' + path] }))
  render(<App queryClient={queryClient} router={router} />)
  return fetcher
}

beforeEach(() => {
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  localStorage.setItem('v2-language', 'en')
})
afterEach(() => {
  cleanup()
  localStorage.clear()
  vi.unstubAllGlobals()
})

it('Observability validates the sample ratio and saves using the original version', async () => {
  const fetcher = open('observability', (url, init) => {
    if (url.pathname === root + '/observability' && init?.method === 'PUT') {
      return Response.json({ ...observation, ...JSON.parse(String(init.body)), version: 4 })
    }
  })
  const ratio = await screen.findByLabelText('Sample ratio', undefined, { timeout: 3000 })
  await waitFor(() => expect(ratio).toHaveProperty('readOnly', false))
  fireEvent.change(ratio, { target: { value: '2' } })
  fireEvent.blur(ratio)
  expect(await screen.findByText('Enter a sample ratio from 0 to 1.')).toBeTruthy()
  fireEvent.change(ratio, { target: { value: '.2' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByText('Saved (version 4).')).toBeTruthy()
  const write = fetcher.mock.calls.find(([, init]) => init?.method === 'PUT')
  expect(JSON.parse(String(write?.[1]?.body))).toMatchObject({ sample_ratio: 0.2, expected_version: 3 })
})

it('Jobs renders declared handlers and warns about queues without a worker group', async () => {
  open('jobs', url => url.pathname === root + '/behavior/jobs' ?
    Response.json({ jobs: { ...jobSettings, worker_groups: [] }, version: 3, updated_at: time }) : undefined)
  expect(await screen.findByText('No worker group serves: default.')).toBeTruthy()
  expect(await screen.findByLabelText('Handler')).toHaveProperty('value', 'send_invoice')
})

it('Workers renders group placement, workflow slots and the advice returned by the API', async () => {
  open('workers')
  expect(await screen.findByRole('table', { name: 'Worker groups' })).toBeTruthy()
  expect(await screen.findByText('workflow-worker · postgres · 2 slots per process')).toBeTruthy()
  expect(await screen.findByText('The database already runs alongside the app.')).toBeTruthy()
})

it('Workflows renders the declared steps and links to Jobs', async () => {
  open('workflows')
  expect(await screen.findByRole('heading', { name: 'Workflow runtime' })).toBeTruthy()
  expect(await screen.findByRole('group', { name: 'Step 1' })).toBeTruthy()
  expect(screen.getByRole('link', { name: 'Jobs and schedules' }).getAttribute('href')).toBe(root + '/jobs')
})

it('Traces rejects malformed JSON and opens a hook span in the section route', async () => {
  open('traces')
  const source = await screen.findByLabelText('Trace document (JSON)')
  fireEvent.change(source, { target: { value: '{' } })
  fireEvent.click(screen.getByRole('button', { name: 'Show trace' }))
  expect(await screen.findByText('This trace could not be shown.')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Load example' }))
  fireEvent.click(await screen.findByRole('button', { name: /hook check_po_match/ }))
  expect((await screen.findByRole('link', { name: 'Open Hooks for hook check_po_match' })).getAttribute('href'))
    .toBe(root + '/hooks?hook=check_po_match')
})

it('Metrics shows grouped values in a report and reads stored history', async () => {
  const fetcher = open('metrics?tab=reports&report=' + report.id)
  const pane = await screen.findByRole('table', { name: 'Run history' })
  expect(within(pane).getByText('600.6 USD')).toBeTruthy()
  expect(fetcher.mock.calls.some(([url]) => new URL(url).search === '?limit=20')).toBe(true)
})

it('Search sends the selected role and reports database coverage', async () => {
  const fetcher = open('search?role=employee&entity=Invoice&q=paid')
  expect(await screen.findByText('1 result')).toBeTruthy()
  expect(await screen.findByText('inv-007')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Reindex' }))
  expect(await screen.findByText('1 record · database index')).toBeTruthy()
  const request = fetcher.mock.calls.map(([url]) => new URL(url)).find(url => url.pathname === root + '/search')
  expect(request?.searchParams.get('as_role')).toBe('employee')
})

it('creates a metric with the typed definition and updates its list', async () => {
  const definition = { key: 'invoice_count', label: 'Invoice count', entity: 'Invoice', agg: 'count', filter: [] }
  const created = { key: definition.key, definition, version: 1, updated_at: time }
  let items: unknown[] = [metric]
  const fetcher = open('metrics', (url, init) => {
    if (url.pathname === root + '/metrics') {
      if (init?.method === 'POST') {
        items = [...items, created]
        return Response.json(created, { status: 201 })
      }
      return Response.json({ items, total: items.length })
    }
    if (url.pathname === root + '/metrics/' + definition.key + '/value') {
      return Response.json({ key: definition.key, version: 1, computed_at: time, value: 3 })
    }
  })
  fireEvent.click(await screen.findByRole('button', { name: 'New metric' }))
  fireEvent.change(await screen.findByLabelText('Key'), { target: { value: 'invoice_count' } })
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Invoice count' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save metric' }))
  expect(await screen.findByText('Invoice count')).toBeTruthy()
  const request = fetcher.mock.calls.find(([url, init]) => new URL(url).pathname === root + '/metrics' && init?.method === 'POST')
  expect(JSON.parse(String(request?.[1]?.body))).toEqual({ definition })
})
