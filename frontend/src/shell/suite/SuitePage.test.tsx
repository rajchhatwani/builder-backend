import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import type { AuthConfig, KeycloakConfig } from '../../api/types'
import { SuitePage } from './SuitePage'

const m = vi.hoisted(() => ({ auth: vi.fn(), kc: vi.fn(), patch: vi.fn(), put: vi.fn(), validate: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({
  ...(await orig<typeof import('../../api/client')>()),
  api: { getAuthConfig: m.auth, getKeycloak: m.kc, updateAuthConfig: m.patch, putKeycloak: m.put, validateProject: m.validate },
}))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const AUTH = (over: Partial<AuthConfig> = {}) => ({ provider: 'keycloak', suite: null, ...over }) as AuthConfig
const KC = { mode: 'own', realm: 'r', api_client_id: 'a', web_client_id: 'w', redirect_uris: [], password_min_length: 12, mfa: 'optional', session_idle_minutes: 30, session_max_hours: 10, audit_retention_days: 90, identity_providers: [], source_project_id: null } as unknown as KeycloakConfig
const SUITE = { suite_id: 'acme', hub_issuer: null, join_state: 'none' as const }

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
async function mount() {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => { root!.render(createElement(SuitePage, { projectId: 'p' })) })
  await act(async () => { await Promise.resolve() })
}
const q = (s: string) => host.querySelector(s) as HTMLElement | null
const btn = (re: RegExp) => [...host.querySelectorAll('button')].find((b) => re.test(b.textContent ?? ''))!
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve() })
const click = async (el: HTMLElement) => { await act(async () => { el.click() }); await flush() }
async function type(el: HTMLInputElement, value: string) {
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  await act(async () => { set.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })) })
}
const setup = (auth = AUTH()) => { m.auth.mockResolvedValue(auth); m.kc.mockResolvedValue(KC); m.validate.mockResolvedValue({ valid: true, issues: [] }) }

afterEach(() => {
  act(() => root?.unmount()); host?.remove(); root = null
  Object.values(m).forEach((f) => f.mockReset())
})

describe('SuitePage', () => {
  it('loads a saved suite into the form with the derived realm', async () => {
    setup(AUTH({ suite: { ...SUITE, join_state: 'planned' } }))
    await mount()
    expect((q('input[type=checkbox]') as HTMLInputElement).checked).toBe(true)
    expect((host.querySelector('input[placeholder=acme]') as HTMLInputElement).value).toBe('acme')
    expect(q('[data-testid=suite-realm]')!.textContent).toBe('suite-acme')
    expect(q('[data-testid=suite-not-keycloak]')).toBeNull()
  })

  it('saves the suite and sets Keycloak to shared with the derived realm', async () => {
    setup()
    m.patch.mockResolvedValue(AUTH({ suite: SUITE }))
    m.put.mockResolvedValue(KC)
    await mount()
    await click(q('input[type=checkbox]')!)
    await type(host.querySelector('input[placeholder=acme]') as HTMLInputElement, 'acme')
    await click(btn(/^Save$/))
    expect(m.patch).toHaveBeenCalledWith('p', { suite: SUITE })
    expect(m.put).toHaveBeenCalledWith('p', expect.objectContaining({ mode: 'shared', realm: 'suite-acme' }))
    expect(q('[data-testid=suite-note]')!.textContent).toBe('Saved.')
  })

  it('shows the server error and the validation messages', async () => {
    setup(AUTH({ suite: SUITE }))
    m.validate.mockResolvedValue({ valid: false, issues: [{ path: 'auth.keycloak.realm', code: 'suite_realm_derived', message: "is derived: it must be 'suite-acme'" }] })
    m.patch.mockRejectedValue(new ApiError(422, { code: 'validation_error', message: 'suite_id is invalid', details: [] }))
    await mount()
    expect(q('[data-testid=suite-issues]')!.textContent).toContain("it must be 'suite-acme'")
    await type(host.querySelector('input[placeholder=acme]') as HTMLInputElement, 'acme2')
    await click(btn(/^Save$/))
    expect(q('[data-testid=suite-error]')!.textContent).toBe('suite_id is invalid')
    expect(m.put).not.toHaveBeenCalled()
  })

  it('warns when the provider is not Keycloak and links to the Keycloak section', async () => {
    setup(AUTH({ provider: 'builtin' }))
    await mount()
    const warn = q('[data-testid=suite-not-keycloak]')!
    expect(warn.textContent).toContain('needs Keycloak')
    expect(warn.querySelector('a')!.getAttribute('href')).toContain('/p/p/keycloak')
  })

  it('removes the project from the suite after a confirmation', async () => {
    setup(AUTH({ suite: SUITE }))
    m.patch.mockResolvedValue(AUTH())
    await mount()
    await click(btn(/Remove from suite/))
    expect(m.patch).not.toHaveBeenCalled()
    await click(btn(/Yes, remove/))
    expect(m.patch).toHaveBeenCalledWith('p', { suite: null })
    expect(m.put).not.toHaveBeenCalled()
    expect(q('[data-testid=suite-note]')!.textContent).toContain('no longer part')
    expect((q('input[type=checkbox]') as HTMLInputElement).checked).toBe(false)
  })

  it('shows a retry when loading fails', async () => {
    m.auth.mockRejectedValue(new Error('boom')); m.kc.mockResolvedValue(KC)
    await mount()
    expect(q('[role=alert]')!.textContent).toContain('boom')
  })
})
