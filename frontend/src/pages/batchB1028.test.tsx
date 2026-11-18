import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Organization, OrgMember, OrgPolicies, ScimConfig } from '../api/types'
import { UiProvider } from '../components/Ui'
import { OrgPoliciesTab } from './OrgPoliciesTab'
import { OrgScimSection } from './OrgScimSection'
import { PeopleTab } from './OrgConsole'

const m = vi.hoisted(() => ({ orgPolicies: vi.fn(), updateOrgPolicies: vi.fn(), scimConfig: vi.fn(), updateScim: vi.fn(), setOrgMemberRole: vi.fn() }))
vi.mock('../api/client', async (orig) => ({ ...(await orig<typeof import('../api/client')>()), api: m }))
vi.mock('../components/AuthProvider', () => ({ useUser: () => ({ id: 'me', email: 'me@x.y', platform_role: 'customer' }) }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) { this.setAttribute('open', '') }
HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) { this.removeAttribute('open') }

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
const tick = (ms = 0) => new Promise((r) => setTimeout(r, ms))
async function mount(el: React.ReactElement) {
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
  await act(async () => { root!.render(createElement(UiProvider, null, el)) })
  await act(async () => { await tick(20) })
}
afterEach(() => { act(() => root?.unmount()); host?.remove(); document.body.innerHTML = ''; root = null; Object.values(m).forEach((f) => f.mockReset()) })
const org = (role: 'owner' | 'admin' | 'member') => ({ id: 'o', name: 'Acme', slug: 'acme', kind: 'team', created_at: '', my_role: role, member_count: 3 }) as Organization
const setVal = async (el: HTMLInputElement | HTMLSelectElement, v: string) => {
  const proto = el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype
  await act(async () => { Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(el, v); el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true })) })
}
const clickEl = async (el: Element) => { await act(async () => { (el as HTMLElement).click(); await tick(10) }) }
const btn = (re: RegExp) => [...document.querySelectorAll('button')].find((b) => re.test(b.textContent ?? '')) as HTMLButtonElement

const POL: OrgPolicies = { require_mfa: false, session_ttl_hours: null, members_without_mfa: 0, default_session_hours: 168, allow_impersonation: true }

describe('B1-028 OrgPoliciesTab', () => {
  it('ttl bounds 1-720 and dirty gate control Save; save sends only the changed field', async () => {
    m.orgPolicies.mockResolvedValue(POL)
    m.updateOrgPolicies.mockResolvedValue({ ...POL, session_ttl_hours: 48 })
    await mount(createElement(OrgPoliciesTab, { org: org('admin'), members: [], onChanged: () => undefined }))
    expect(btn(/Save policies/).disabled).toBe(true) // clean
    await clickEl(document.querySelectorAll('input[name="ttl"]')[1])
    const hours = document.querySelector('input[type="number"]') as HTMLInputElement
    expect(hours.value).toBe('24')
    for (const bad of ['0', '721', '1.5', '']) {
      await setVal(hours, bad)
      expect(btn(/Save policies/).disabled).toBe(true)
    }
    for (const ok of ['1', '720']) {
      await setVal(hours, ok)
      expect(btn(/Save policies/).disabled).toBe(false)
    }
    await setVal(hours, '48')
    await clickEl(btn(/Save policies/))
    expect(m.updateOrgPolicies).toHaveBeenCalledWith('acme', { session_ttl_hours: 48 })
  })
})

const CFG = (group_roles: Record<string, 'owner' | 'admin' | 'member'>): ScimConfig => ({
  configured: true, allowed_by_plan: true, active: true, base_url: 'b', users_url: 'u', token_hint: 'abcd', token_created_at: null,
  created_at: null, last_sync_at: null, group_roles, groups: [], active_users: 0, deactivated_users: 0,
}) as ScimConfig

describe('B1-028 OrgScimSection', () => {
  it('admin is locked out of a dictionary that maps Owner; owner can edit', async () => {
    m.scimConfig.mockResolvedValue(CFG({ ops: 'owner' }))
    await mount(createElement(OrgScimSection, { org: org('admin'), verifiedDomains: 1, ssoActive: true }))
    expect(document.body.textContent).toContain('Only an owner can map a group to Owner')
    expect((document.querySelector('input[aria-label="Group name"]') as HTMLInputElement).disabled).toBe(true)
    expect(btn(/Save mappings/)).toBeUndefined()
    act(() => root?.unmount()); host.remove(); root = null
    await mount(createElement(OrgScimSection, { org: org('owner'), verifiedDomains: 1, ssoActive: true }))
    expect((document.querySelector('input[aria-label="Group name"]') as HTMLInputElement).disabled).toBe(false)
    expect(btn(/Save mappings/)).toBeDefined()
  })

  it('admin role picker has no Owner; duplicate names (case-insensitive) block Save', async () => {
    m.scimConfig.mockResolvedValue(CFG({}))
    await mount(createElement(OrgScimSection, { org: org('admin'), verifiedDomains: 1, ssoActive: true }))
    await clickEl(btn(/Add mapping/))
    const opts = [...document.querySelectorAll('select[aria-label^="Role for"] option')].map((o) => o.textContent)
    expect(opts).toEqual(['Admin', 'Member'])
    await setVal(document.querySelector('input[aria-label="Group name"]') as HTMLInputElement, 'Ops')
    await clickEl(btn(/Add mapping/))
    await setVal(document.querySelectorAll('input[aria-label="Group name"]')[1] as HTMLInputElement, 'ops')
    expect(document.body.textContent).toContain('is listed twice')
    expect(btn(/Save mappings/).disabled).toBe(true)
  })
})

const mem = (id: string, role: OrgMember['role']): OrgMember => ({ user_id: id, email: `${id}@x.y`, name: '', role, joined_at: '2026-01-01T00:00:00Z' })

describe('B1-028 PeopleTab roleChoices', () => {
  const members = [mem('me', 'admin'), mem('own', 'owner'), mem('adm', 'admin'), mem('mem', 'member')]
  const choices = (email: string) => [...(document.querySelector(`select[aria-label="Role of ${email}"]`)?.querySelectorAll('option') ?? [])].map((o) => o.textContent)
  const has = (email: string) => document.querySelector(`select[aria-label="Role of ${email}"]`) !== null

  it('admin: no select for self or owners; Admin/Member for others', async () => {
    await mount(createElement(PeopleTab, { org: org('admin'), members, onChanged: () => undefined }))
    expect(has('me@x.y')).toBe(false)
    expect(has('own@x.y')).toBe(false)
    expect(choices('adm@x.y')).toEqual(['Admin', 'Member'])
    expect(choices('mem@x.y')).toEqual(['Admin', 'Member'])
  })

  it('owner: may change another owner (3 choices); plain member gets no selects', async () => {
    await mount(createElement(PeopleTab, { org: org('owner'), members: [mem('me', 'owner'), ...members.slice(1)], onChanged: () => undefined }))
    expect(choices('own@x.y')).toEqual(['Owner', 'Admin', 'Member'])
    expect(has('me@x.y')).toBe(false)
    act(() => root?.unmount()); host.remove(); root = null
    await mount(createElement(PeopleTab, { org: org('member'), members, onChanged: () => undefined }))
    expect(document.querySelectorAll('select').length).toBe(0)
  })
})
