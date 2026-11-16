import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { UiProvider } from '../components/Ui'
import { AdminApp } from './admin/AdminApp'
import { AdminInsightsPage, AdminPlans, AdminProjects } from './admin/AdminPages'
import { ProjectsPage } from './ProjectsPage'
import { AccountPage } from './AccountPage'

const m = vi.hoisted(() => ({
  adminProjects: vi.fn(), adminInsights: vi.fn(), adminPlans: vi.fn(), adminLogout: vi.fn(), adminResume: vi.fn(),
  listProjects: vi.fn(), listOrgs: vi.fn(), mfaStatus: vi.fn(), deleteProject: vi.fn(),
  listApiTokens: vi.fn(), revokeApiToken: vi.fn(), logoutEverywhere: vi.fn(),
}))
vi.mock('../api/client', async (orig) => ({ ...(await orig<typeof import('../api/client')>()), api: new Proxy(m as Record<string, unknown>, { get: (t, k: string) => t[k] ?? (() => new Promise(() => undefined)) }) }))
vi.mock('../components/AuthProvider', () => ({ useUser: () => ({ id: 'u', email: 'a@b.c', platform_role: 'customer' }), useAuth: () => ({ setUser() {}, state: { status: 'user' } }) }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) { this.setAttribute('open', '') }
HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) { this.removeAttribute('open'); this.dispatchEvent(new Event('close')) }

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
const tick = (ms = 0) => new Promise((r) => setTimeout(r, ms))
async function mount(el: React.ReactElement) {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => { root!.render(createElement(UiProvider, null, el)) })
  await act(async () => { await tick(260) })
}
const btn = (re: RegExp) => [...document.querySelectorAll('button')].find((b) => re.test(b.textContent ?? ''))!
const click = async (el: Element) => { await act(async () => { (el as HTMLElement).click(); await tick(10) }) }
afterEach(() => { act(() => root?.unmount()); host?.remove(); document.body.innerHTML = ''; root = null; Object.values(m).forEach((f) => f.mockReset()) })
const page = (names: string[]) => ({ items: names.map((n) => ({ id: n, name: n, slug: n, owner_emails: [], entity_count: 0, relation_count: 0, created_at: '2026-01-01T00:00:00Z' })), total: names.length, limit: 25, offset: 0 })

describe('B1-042', () => {
  it('F-0546 a slow older admin query does not overwrite the newest one', async () => {
    let slow!: (v: unknown) => void
    m.adminProjects.mockImplementationOnce(() => new Promise((r) => { slow = r }))
    m.adminProjects.mockResolvedValue(page(['fresh']))
    await mount(createElement(AdminProjects))
    const input = document.querySelector('input[type=search]') as HTMLInputElement
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'x')
      input.dispatchEvent(new Event('input', { bubbles: true }))
      await tick(260)
    })
    expect(host.textContent).toContain('fresh')
    await act(async () => { slow(page(['stale'])); await tick(10) })
    expect(host.textContent).toContain('fresh')
    expect(host.textContent).not.toContain('stale')
  })

  it('F-0548 failed loads show a retryable error, not blank/empty/forever-loading', async () => {
    m.adminInsights.mockRejectedValue(new ApiError(500, { code: 'x', message: 'boom', details: [] }))
    await mount(createElement(AdminInsightsPage))
    expect(document.querySelector('[role=alert]')).not.toBeNull()
    expect(host.textContent).not.toContain('Loading')
    act(() => root!.unmount()); host.remove()
    m.adminPlans.mockRejectedValue(new ApiError(500, { code: 'x', message: 'boom', details: [] }))
    await mount(createElement(AdminPlans, { readOnly: false }))
    expect(document.querySelector('[role=alert]')).not.toBeNull()
    expect(btn(/New plan/)).toBeUndefined()
    act(() => root!.unmount()); host.remove()
    m.adminProjects.mockRejectedValue(new ApiError(500, { code: 'x', message: 'boom', details: [] }))
    await mount(createElement(AdminProjects))
    expect(document.querySelector('[role=alert]')).not.toBeNull()
  })

  it('F-0547 Sign out leaves the console even if the logout request fails', async () => {
    m.adminResume.mockResolvedValue({ id: 'u', email: 'a@b.c', platform_role: 'platform_admin' })
    m.adminLogout.mockRejectedValue(new Error('net'))
    const unhandled = vi.fn()
    process.on('unhandledRejection', unhandled)
    await mount(createElement(AdminApp, { section: 'overview' as never }))
    await click(btn(/^Sign out$/))
    process.off('unhandledRejection', unhandled)
    expect(btn(/^Sign out$/)).toBeUndefined()
    expect(unhandled).not.toHaveBeenCalled()
  })

  it('F-0549 a failed project delete is reported, not silent', async () => {
    m.listProjects.mockResolvedValue({ items: [{ id: 'p1', name: 'Demo', slug: 'demo', organization_id: null, role: 'owner' }], total: 1 })
    m.listOrgs.mockResolvedValue({ items: [] })
    m.deleteProject.mockRejectedValue(new ApiError(423, { code: 'x', message: 'org locked', details: [] }))
    await mount(createElement(ProjectsPage))
    await click(btn(/^Delete$/))
    await click(btn(/Delete project/))
    expect(m.deleteProject).toHaveBeenCalled()
    expect(document.body.textContent).toMatch(/locked|reach the server/)
  })

  it('F-0550 failed revoke / sign-out-everywhere tell the user', async () => {
    const tok = { id: 't1', name: 'ci', prefix: 'x', project_id: null, created_at: '2026-01-01T00:00:00Z', expires_at: '2099-01-01T00:00:00Z', revoked_at: null, last_used_at: null, scopes: [] }
    m.mfaStatus.mockReturnValue(new Promise(() => undefined))
    m.listApiTokens.mockResolvedValue([tok])
    m.listProjects.mockResolvedValue({ items: [], total: 0 })
    m.revokeApiToken.mockRejectedValue(new ApiError(500, { code: 'x', message: 'nope', details: [] }))
    m.logoutEverywhere.mockRejectedValue(new ApiError(500, { code: 'x', message: 'nope2', details: [] }))
    await mount(createElement(AccountPage))
    await click(btn(/^Revoke$/))
    await click(btn(/Revoke token/))
    expect(document.body.textContent).not.toContain('Token revoked.')
    expect(document.body.textContent).toContain('nope')
    await click(btn(/^Sign out everywhere$/))
    await click([...document.querySelectorAll('dialog button')].find((b) => /Sign out everywhere/.test(b.textContent ?? '')) as Element)
    expect(document.body.textContent).toContain('nope2')
  })
})
