import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { WebhookSubscriptions } from './WebhookSubscriptions'

const m = vi.hoisted(() => ({ list: vi.fn(), inbound: vi.fn(), create: vi.fn(), rotate: vi.fn(), setEnabled: vi.fn(), remove: vi.fn(), setInboundSecret: vi.fn(), confirm: vi.fn() }))
vi.mock('./webhookApi', () => ({ webhookApi: m, WebhookApiError: class extends Error {} }))
vi.mock('../../components/Ui', () => ({ useUi: () => ({ confirm: m.confirm, toast: vi.fn() }) }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const SUB = { id: 's1', url: 'https://hooks.example.com/a', description: '', event_types: ['order.created'], status: 'active', disabled_reason: null, consecutive_failures: 0, secret_version: 1, rotating: false, created_at: 'x' }
const SECRET = 'whsec_ONLY_SHOWN_ONCE_123'

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
const btn = (re: RegExp) => [...host.querySelectorAll('button')].find((b) => re.test(b.textContent ?? b.getAttribute('aria-label') ?? '') || re.test(b.getAttribute('aria-label') ?? ''))!
const type = async (el: HTMLInputElement, v: string) => {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(el, v)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
async function mountConnected() {
  m.list.mockResolvedValue([SUB])
  m.inbound.mockResolvedValue([])
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => { root!.render(createElement(WebhookSubscriptions, { origin: 'http://localhost:9999', events: ['order.created'], inbound: [] })) })
  await type(host.querySelector<HTMLInputElement>('#wh-token')!, 'admin-token-value')
  await act(async () => { btn(/Load subscriptions/).click() })
  await act(async () => { await Promise.resolve() })
}
afterEach(() => { act(() => root?.unmount()); host?.remove(); root = null; Object.values(m).forEach((f) => f.mockReset()); localStorage.clear(); sessionStorage.clear() })

describe('WebhookSubscriptions', () => {
  it('rotating shows the new secret once, then removes it from the page; nothing is stored', async () => {
    await mountConnected()
    expect(host.querySelector('[data-testid=wh-table]')?.textContent).toContain('hooks.example.com')
    m.confirm.mockResolvedValue(true)
    m.rotate.mockResolvedValue({ ...SUB, secret_version: 2, rotating: true, secret: SECRET })
    await act(async () => { btn(/Rotate the secret of/).click() })
    await act(async () => { await Promise.resolve() })
    expect(m.rotate).toHaveBeenCalledWith({ origin: 'http://localhost:9999', token: 'admin-token-value' }, 's1')
    expect(host.querySelector('[data-testid=wh-secret-value]')?.textContent).toBe(SECRET)
    await act(async () => { btn(/I have stored it/).click() })
    expect(host.textContent).not.toContain(SECRET)
    expect(JSON.stringify({ ...localStorage })).not.toContain(SECRET)
    expect(JSON.stringify({ ...sessionStorage })).not.toContain(SECRET)
    expect(JSON.stringify({ ...localStorage })).not.toContain('admin-token-value')
  })

  it('does nothing when the rotate confirmation is cancelled', async () => {
    await mountConnected()
    m.confirm.mockResolvedValue(false)
    await act(async () => { btn(/Rotate the secret of/).click() })
    expect(m.rotate).not.toHaveBeenCalled()
    expect(host.querySelector('[data-testid=wh-secret]')).toBeNull()
  })

  it('clears an undismissed secret after the time limit', async () => {
    vi.useFakeTimers()
    try {
      await mountConnected()
      m.create.mockResolvedValue({ ...SUB, secret: SECRET })
      await type(host.querySelector<HTMLInputElement>('#wh-url')!, 'https://hooks.example.com/b')
      await act(async () => { host.querySelector<HTMLInputElement>('input[type=checkbox]')!.click() })
      await act(async () => { btn(/Create subscription/).click() })
      await act(async () => { await Promise.resolve() })
      expect(host.textContent).toContain(SECRET)
      await act(async () => { vi.advanceTimersByTime(5 * 60_000 + 10) })
      expect(host.textContent).not.toContain(SECRET)
    } finally {
      vi.useRealTimers()
    }
  })

  it('shows an API error without a secret in it', async () => {
    m.list.mockRejectedValue(new Error('The generated API answered 401'))
    m.inbound.mockResolvedValue([])
    host = document.createElement('div')
    document.body.appendChild(host)
    root = createRoot(host)
    await act(async () => { root!.render(createElement(WebhookSubscriptions, { origin: 'http://localhost:9999', events: [], inbound: [] })) })
    await type(host.querySelector<HTMLInputElement>('#wh-token')!, 'bad')
    await act(async () => { btn(/Load subscriptions/).click() })
    await act(async () => { await Promise.resolve() })
    expect(host.querySelector('[data-testid=wh-error]')?.textContent).toContain('401')
    expect(host.querySelector('[data-testid=wh-table]')).toBeNull()
  })

  it('still shows the one-time secret when the list refresh fails after create or rotate (M-1)', async () => {
    await mountConnected()
    m.confirm.mockResolvedValue(true)
    m.rotate.mockResolvedValue({ ...SUB, secret_version: 2, rotating: true, secret: SECRET })
    m.list.mockRejectedValue(new Error('refresh down'))
    await act(async () => { btn(/Rotate the secret of/).click() })
    await act(async () => { await Promise.resolve() })
    expect(host.querySelector('[data-testid=wh-secret-value]')?.textContent).toBe(SECRET)
    expect(host.querySelector('[data-testid=wh-error]')?.textContent).toContain('could not be refreshed')
  })

  it('empties the token input once connected', async () => {
    await mountConnected()
    expect(host.querySelector('#wh-token')).toBeNull()
  })
})
