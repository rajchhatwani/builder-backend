import { createElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { byText, click, flush, mount } from '../shell/ai/testUtils'
import { ProjectsPage } from './ProjectsPage'
import { AccountPage } from './AccountPage'

const m = vi.hoisted(() => ({
  listProjects: vi.fn(), listOrgs: vi.fn(), mfaStatus: vi.fn(), listEntities: vi.fn(), getAuthConfig: vi.fn(), validateProject: vi.fn(),
  listApiTokens: vi.fn(), revokeApiToken: vi.fn(),
}))
vi.mock('../api/client', async (orig) => ({ ...(await orig<typeof import('../api/client')>()), api: m }))
vi.mock('../components/Ui', () => ({ useUi: () => ({ confirm: async () => true, toast: () => {} }) }))
vi.mock('../components/AuthProvider', () => ({ useUser: () => ({ email: 'a@b.c', platform_role: 'customer' }) }))
vi.mock('../components/PasswordForm', () => ({ PasswordForm: () => null }))
vi.mock('../components/TwoFactorSection', () => ({ TwoFactorSection: () => null }))

const project = { id: 'p1', name: 'Demo', description: '', updated_at: '2026-01-01T00:00:00Z' }
beforeEach(() => {
  Object.values(m).forEach((f) => f.mockReset())
  m.listProjects.mockResolvedValue({ items: [project], total: 1 })
  m.listOrgs.mockResolvedValue({ items: [] })
  m.getAuthConfig.mockResolvedValue({ enabled: false })
  m.validateProject.mockResolvedValue({ issues: [] })
})

describe('ProjectsPage card summary (F-1248)', () => {
  it('shows a neutral fallback, not Loading forever, when the entity request fails', async () => {
    m.listEntities.mockRejectedValue(new Error('boom'))
    const host = await mount(createElement(ProjectsPage))
    await flush()
    expect(host.textContent).not.toContain('Loading…')
    expect(host.textContent).toContain('Summary unavailable')
  })
})

describe('AccountPage tokens (F-1250)', () => {
  it('shows an error with Retry instead of "No active tokens." when loading fails', async () => {
    m.listApiTokens.mockRejectedValueOnce(new Error('boom'))
    m.listProjects.mockResolvedValue({ items: [], total: 0 })
    const host = await mount(createElement(AccountPage))
    expect(host.textContent).not.toContain('No active tokens.')
    const retry = byText(host, 'button', /Retry/)
    expect(retry).toBeTruthy()
    m.listApiTokens.mockResolvedValue([])
    await click(retry!)
    expect(host.textContent).toContain('No active tokens.')
  })

  it('does not leak an unhandled rejection when a reload after revoke fails', async () => {
    const tok = { id: 't1', scopes: ['read'], description: null, last_mcp_used_at: null, name: 'ci', revoked_at: null, expires_at: '2999-01-01T00:00:00Z', created_at: '', last_used_at: null, project_id: null }
    m.listApiTokens.mockResolvedValueOnce([tok]).mockRejectedValue(new Error('boom'))
    m.revokeApiToken.mockResolvedValue(undefined)
    m.listProjects.mockResolvedValue({ items: [], total: 0 })
    const unhandled = vi.fn()
    process.on('unhandledRejection', unhandled)
    const host = await mount(createElement(AccountPage))
    await click(byText(host, 'button', /Revoke/)!)
    await flush(10)
    await new Promise((r) => setTimeout(r, 10))
    process.off('unhandledRejection', unhandled)
    expect(unhandled).not.toHaveBeenCalled()
    expect(byText(host, 'button', /Retry/)).toBeTruthy()
  })
})
