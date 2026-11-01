import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { NotificationsPage } from './NotificationsPage'

const m = vi.hoisted(() => ({ spec: vi.fn() }))
vi.mock('../../api/client', () => ({ api: { getSpecJson: m.spec } }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const SPEC = {
  notifications: {
    enabled: true,
    types: [{
      name: 'order_shipped', category: 'optional', channels: ['email'], variables: ['order_number'], default_enabled: true,
      templates: [{ channel: 'email', subject: 'Order {{ order_number }}', body: 'Shipped {{ order_number }}', html: false }],
    }],
  },
}

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
async function mount() {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => { root!.render(createElement(NotificationsPage, { projectId: 'p' })) })
  await act(async () => { await Promise.resolve() })
}
const q = (s: string) => host.querySelector(s) as HTMLElement | null
const btn = (re: RegExp) => [...host.querySelectorAll('button')].find((b) => re.test(b.textContent ?? ''))!
async function type(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  await act(async () => {
    Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(el, value)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

afterEach(() => { act(() => root?.unmount()); host?.remove(); root = null; m.spec.mockReset(); localStorage.clear() })

describe('NotificationsPage', () => {
  it('shows an empty state and an example when the spec declares nothing', async () => {
    m.spec.mockResolvedValue({})
    await mount()
    expect(q('[data-testid=notif-empty]')).not.toBeNull()
    await act(async () => { btn(/Try with an example/).click() })
    expect(q('[data-testid=notif-example]')).not.toBeNull()
    expect(q('#nt-body')).not.toBeNull()
  })

  it('shows a retryable error', async () => {
    m.spec.mockRejectedValueOnce(new Error('boom')).mockResolvedValue(SPEC)
    await mount()
    expect(q('[role=alert]')?.textContent).toContain('boom')
    await act(async () => { btn(/Try again/).click() })
    expect(q('#nt-body')).not.toBeNull()
  })

  it('edits, previews as plain text, blocks bad placeholders, saves a draft', async () => {
    m.spec.mockResolvedValue(SPEC)
    await mount()
    expect(q('[data-testid=nt-variables]')?.textContent).toContain('{{ order_number }}')
    expect(q('[data-testid=nt-preview-body]')?.textContent).toBe('Shipped Sample order number')
    const body = q('#nt-body') as HTMLTextAreaElement
    await type(body, '<img src=x onerror=alert(1)> {{ order_number }}')
    expect(q('[data-testid=nt-preview-body]')?.textContent).toBe('<img src=x onerror=alert(1)> Sample order number')
    expect(q('[data-testid=nt-preview-body] img')).toBeNull()
    await type(body, 'Hi {{ secret }}')
    expect(q('[data-testid=nt-problems]')?.textContent).toContain('not a declared variable')
    await act(async () => { btn(/Save template/).click() })
    expect(localStorage.getItem('notif.drafts.p')).toBeNull()
    await type(body, 'Sent {{ order_number }}')
    await act(async () => { btn(/Save template/).click() })
    expect(q('[data-testid=nt-saved]')?.textContent).toContain('order_shipped / email')
    expect(JSON.parse(localStorage.getItem('notif.drafts.p')!)['order_shipped/email'].body).toBe('Sent {{ order_number }}')
  })

  it('shows the preferences matrix and the empty delivery log', async () => {
    m.spec.mockResolvedValue(SPEC)
    await mount()
    await act(async () => { btn(/Preferences/).click() })
    expect(q('[data-testid=nt-matrix]')?.textContent).toContain('On by default, user can opt out')
    await act(async () => { btn(/Delivery log/).click() })
    expect(q('[data-testid=nt-log-empty]')).not.toBeNull()
  })
})
