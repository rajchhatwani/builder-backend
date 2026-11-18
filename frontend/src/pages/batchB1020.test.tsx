import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { UiProvider } from '../components/Ui'
import { AdminSettings, UserTokensDialog } from './admin/AdminPages'

const m = vi.hoisted(() => ({ adminSettings: vi.fn(), adminListUserTokens: vi.fn() }))
vi.mock('../api/client', async (orig) => ({ ...(await orig<typeof import('../api/client')>()), api: new Proxy(m as Record<string, unknown>, { get: (t, k: string) => t[k] ?? (() => new Promise(() => undefined)) }) }))
vi.mock('../components/AuthProvider', () => ({ useUser: () => ({ id: 'u', email: 'a@b.c', platform_role: 'platform_admin' }), useAuth: () => ({ setUser() {}, state: { status: 'user' } }) }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) { this.setAttribute('open', '') }
HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) { this.removeAttribute('open'); this.dispatchEvent(new Event('close')) }

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
const tick = (ms = 0) => new Promise((r) => setTimeout(r, ms))
const render = async (el: React.ReactElement) => { await act(async () => { root!.render(createElement(UiProvider, null, el)); await tick(20) }) }
afterEach(() => { act(() => root?.unmount()); host?.remove(); document.body.innerHTML = ''; root = null; Object.values(m).forEach((f) => f.mockReset()) })
function setup() { host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host) }
const user = (id: string) => ({ id, email: `${id}@x.io` }) as never
const tok = (id: string, name: string) => ({ id, name, created_at: '2026-01-01T00:00:00Z', scopes: [], last_used_at: null, expires_at: null })

describe('B1-020', () => {
  it('F-1267 AdminSettings shows a retryable error when the load fails', async () => {
    m.adminSettings.mockRejectedValueOnce(new ApiError(500, { code: 'x', message: 'boom', details: [] }))
    setup()
    await render(createElement(AdminSettings))
    expect(document.querySelector('[role=alert]')).not.toBeNull()
    expect(host.textContent).toContain('boom')
  })

  it('F-1269 a late token list of the previous user is ignored', async () => {
    let slowA!: (v: unknown) => void
    m.adminListUserTokens.mockImplementation((id: string) => id === 'A' ? new Promise((r) => { slowA = r }) : Promise.resolve([tok('tb', 'b-token')]))
    setup()
    const props = { open: true, onClose: () => undefined }
    await render(createElement(UserTokensDialog, { ...props, user: user('A') }))
    await render(createElement(UserTokensDialog, { ...props, user: user('B') }))
    await act(async () => { slowA([tok('ta', 'a-token')]); await tick(10) })
    expect(host.textContent).toContain('b-token')
    expect(host.textContent).not.toContain('a-token')
  })
})
