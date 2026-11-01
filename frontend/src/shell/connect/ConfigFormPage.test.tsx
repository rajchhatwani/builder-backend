import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { pickWritable } from './ConfigFormPage'
import { PaymentsFormPage, DeploymentFormPage } from './ConfigPages'
import payments from '../../forms/schemas/payments.json'
import type { JsonSchema } from '../../forms'

const m = vi.hoisted(() => ({ getPayments: vi.fn(), putPayments: vi.fn(), getDeployment: vi.fn(), putDeployment: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({ ...(await orig<typeof import('../../api/client')>()), api: m }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const PAY = {
  id: 'x', project_id: 'p', enabled: true, provider: 'stripe', payable: null, currencies: ['usd'], max_amount_minor: 5000,
  success_urls: [], cancel_urls: [], roles: { create: [], read: [], read_all: [], refund: [], approve_refund: [], operate: [] },
  refund_approval_threshold_minor: null, scale: { profile: 'small', db_max_connections: 100, availability: 'single', pgbouncer: false, kubernetes: false, webhook_events_retention_days: 90, jobs_retention_days: 30 },
  security: { webhook_tolerance_seconds: 300 }, created_at: 'a', updated_at: 'b',
}

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
async function mount(el: ReturnType<typeof createElement>) {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => { root!.render(el) })
  await act(async () => { await Promise.resolve() })
}
const btn = (re: RegExp) => [...host.querySelectorAll('button')].find((b) => re.test(b.textContent ?? ''))!
const type = async (el: HTMLInputElement, v: string) => {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(el, v)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
afterEach(() => { act(() => root?.unmount()); host?.remove(); root = null; Object.values(m).forEach((f) => f.mockReset()); localStorage.clear() })

describe('pickWritable', () => {
  it('keeps only properties of the write schema (no id, timestamps or enabled)', () => {
    const w = pickWritable(payments as JsonSchema, PAY)
    expect(Object.keys(w)).not.toContain('id')
    expect(Object.keys(w)).not.toContain('enabled')
    expect(Object.keys(w)).not.toContain('created_at')
    expect(w.provider).toBe('stripe')
  })
})

describe('Payments form page', () => {
  it('shows a loading then the generated form with the switch state', async () => {
    m.getPayments.mockResolvedValue(PAY)
    await mount(createElement(PaymentsFormPage, { projectId: 'p' }))
    expect(host.querySelector('h1')?.textContent).toBe('Payments')
    expect(host.querySelector('[data-schema-form]')).not.toBeNull()
    expect(host.querySelector('[data-testid=config-status]')?.textContent).toContain('switched on')
    expect(btn(/^Save$/).disabled).toBe(true) // nothing changed yet
  })

  it('saves the edited writable fields only', async () => {
    m.getPayments.mockResolvedValue(PAY)
    m.putPayments.mockImplementation(async (_p: string, b: Record<string, unknown>) => ({ ...PAY, ...b }))
    await mount(createElement(PaymentsFormPage, { projectId: 'p' }))
    await type(host.querySelector<HTMLInputElement>('#cf-payments-max_amount_minor')!, '9000')
    await act(async () => { btn(/^Save$/).click() })
    expect(m.putPayments).toHaveBeenCalledTimes(1)
    const body = m.putPayments.mock.calls[0][1] as Record<string, unknown>
    expect(body.max_amount_minor).toBe(9000)
    expect(body).not.toHaveProperty('id')
    expect(body).not.toHaveProperty('expected_version')
    expect(host.querySelector('[data-testid=save-note]')?.textContent).toBe('Saved.')
  })

  it('shows the backend 422 message next to the field, verbatim', async () => {
    m.getPayments.mockResolvedValue(PAY)
    m.putPayments.mockRejectedValue(new ApiError(422, { code: 'validation_error', message: 'Request validation failed', details: [{ loc: ['body', 'max_amount_minor'], msg: 'Input should be greater than or equal to 1' }] }))
    await mount(createElement(PaymentsFormPage, { projectId: 'p' }))
    await type(host.querySelector<HTMLInputElement>('#cf-payments-max_amount_minor')!, '7')
    await act(async () => { btn(/^Save$/).click() })
    expect(host.querySelector('#cf-payments-max_amount_minor-err')?.textContent).toBe('Input should be greater than or equal to 1')
  })

  it('shows a retryable error when loading fails', async () => {
    m.getPayments.mockRejectedValueOnce(new Error('down')).mockResolvedValue(PAY)
    await mount(createElement(PaymentsFormPage, { projectId: 'p' }))
    expect(host.querySelector('[role=alert]')?.textContent).toContain('down')
    await act(async () => { btn(/Try again/).click() })
    expect(host.querySelector('[data-schema-form]')).not.toBeNull()
  })

  it('"Use the classic panel" turns the page flag off', async () => {
    localStorage.setItem('ui.payments', 'v2')
    m.getPayments.mockResolvedValue(PAY)
    const reload = vi.fn()
    Object.defineProperty(window, 'location', { configurable: true, value: { ...window.location, reload } })
    await mount(createElement(PaymentsFormPage, { projectId: 'p' }))
    await act(async () => { btn(/classic panel/).click() })
    expect(localStorage.getItem('ui.payments')).toBe('classic')
    expect(reload).toHaveBeenCalled()
  })
})

describe('versioned pages (Deploy)', () => {
  it('sends expected_version and reports a 409 as a conflict', async () => {
    m.getDeployment.mockResolvedValue({ project_id: 'p', enabled: true, cloud: 'aws', region: '', github_repo: '', environments: [], version: 4, updated_at: null })
    m.putDeployment.mockRejectedValue(new ApiError(409, { code: 'conflict', message: 'stale', details: [] }))
    await mount(createElement(DeploymentFormPage, { projectId: 'p' }))
    await type(host.querySelector<HTMLInputElement>('#cf-deployment-region')!, 'eu-west-1')
    await act(async () => { btn(/^Save$/).click() })
    expect((m.putDeployment.mock.calls[0][1] as Record<string, unknown>).expected_version).toBe(4)
    expect(host.querySelector('[data-testid=conflict]')).not.toBeNull()
  })
})

describe('never-saved settings (404)', () => {
  it('starts from the schema defaults, says so, and allows the first save', async () => {
    m.getPayments.mockRejectedValue(new ApiError(404, { code: 'not_found', message: 'payments settings not found', details: [] }))
    m.putPayments.mockImplementation(async (_p: string, b: Record<string, unknown>) => ({ ...PAY, ...b }))
    await mount(createElement(PaymentsFormPage, { projectId: 'p' }))
    expect(host.querySelector('[data-testid=config-fresh]')).not.toBeNull()
    expect(btn(/^Save$/).disabled).toBe(false)
    await act(async () => { btn(/^Save$/).click() })
    expect(m.putPayments).toHaveBeenCalledTimes(1)
    expect(host.querySelector('[data-testid=config-fresh]')).toBeNull()
  })
})
