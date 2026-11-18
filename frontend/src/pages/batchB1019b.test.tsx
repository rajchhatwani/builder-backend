import { createElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { byText, click, flush, mount } from '../shell/ai/testUtils'
import { OrgConsole, timeLeft } from './OrgConsole'
import { tokenFrom } from './InvitationsPage'

const m = vi.hoisted(() => ({
  getOrg: vi.fn(), orgMembers: vi.fn(), orgPlan: vi.fn(), orgInvitations: vi.fn(), revokeOrgInvitation: vi.fn(), resendOrgInvitation: vi.fn(),
}))
vi.mock('../api/client', async (orig) => ({ ...(await orig<typeof import('../api/client')>()), api: m }))
vi.mock('../components/Ui', () => ({ useUi: () => ({ confirm: async () => true, toast: () => {} }) }))
vi.mock('../components/AuthProvider', () => ({ useUser: () => ({ id: 'u1', email: 'a@b.c', platform_role: 'customer' }) }))

const ORG = { id: 'o', name: 'Acme', slug: 'acme', kind: 'team', created_at: '', my_role: 'admin', member_count: 1 }
const INV = { id: 'i1', email: 'x@y.z', role: 'member', status: 'pending', expires_at: '2999-01-01T00:00:00Z' }
beforeEach(() => {
  Object.values(m).forEach((f) => f.mockReset())
  m.getOrg.mockResolvedValue(ORG)
  m.orgMembers.mockResolvedValue({ items: [] })
  m.orgPlan.mockResolvedValue(null)
})

describe('InvitesTab load errors (F-1249)', () => {
  it('shows the error with Retry instead of Loading forever; retry recovers', async () => {
    m.orgInvitations.mockRejectedValueOnce(new Error('boom')).mockResolvedValue({ items: [INV] })
    const host = await mount(createElement(OrgConsole, { slug: 'acme', tab: 'invites' }))
    await flush()
    expect(host.textContent).not.toContain('Loading…')
    const retry = byText(host, 'button', /Retry/)
    expect(retry).toBeTruthy()
    await click(retry!)
    expect(host.textContent).toContain('x@y.z')
  })

  it('a successful revoke clears an earlier action error', async () => {
    m.orgInvitations.mockResolvedValue({ items: [INV] })
    m.resendOrgInvitation.mockRejectedValueOnce(new Error('boom'))
    m.revokeOrgInvitation.mockResolvedValue(undefined)
    const host = await mount(createElement(OrgConsole, { slug: 'acme', tab: 'invites' }))
    await click(byText(host, 'button', /Resend/)!)
    expect(host.querySelector('[role=alert]')).not.toBeNull()
    await click(byText(host, 'button', /Revoke/)!)
    expect(host.querySelector('[role=alert]')).toBeNull()
  })
})

describe('pure helpers (F-1251)', () => {
  it('tokenFrom takes a pasted link or a bare token', () => {
    expect(tokenFrom('  https://x/#/invite/abc%20d?z=1 ')).toBe('abc d')
    expect(tokenFrom(' rawtoken ')).toBe('rawtoken')
  })
  it('timeLeft formats days, hours and expiry', () => {
    const now = Date.UTC(2026, 0, 1)
    expect(timeLeft(new Date(now - 1).toISOString(), now)).toBe('expired')
    expect(timeLeft(new Date(now + 30 * 60_000).toISOString(), now)).toBe('1 hour left')
    expect(timeLeft(new Date(now + 5 * 3_600_000).toISOString(), now)).toBe('5 hours left')
    expect(timeLeft(new Date(now + 86_400_000).toISOString(), now)).toBe('1 day left')
    expect(timeLeft(new Date(now + 3 * 86_400_000).toISOString(), now)).toBe('3 days left')
  })
})
