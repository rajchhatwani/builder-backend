import { act, createElement } from 'react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { ShellV2 } from './ShellV2'
import { RAIL_GROUPS } from './groups'
import { mount, flush } from './ai/testUtils'

const auth = vi.hoisted(() => ({ role: 'customer' as string }))
vi.mock('../components/AuthProvider', () => ({
  useAuth: () => ({ state: { status: 'user', user: { id: 'u', email: 'u@x.io', platform_role: auth.role } }, signOut: vi.fn() }),
}))
vi.mock('../realtime/LiveIndicator', () => ({ LiveIndicator: () => null }))
vi.mock('./workbench/WorkbenchDrawer', () => ({ WorkbenchDrawer: () => null }))

beforeAll(() => {
  window.matchMedia ||= ((q: string) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} })) as never
  const d = HTMLDialogElement.prototype as unknown as { showModal?: () => void; close?: () => void }
  d.showModal ||= function (this: HTMLDialogElement) { this.setAttribute('open', '') }
  d.close ||= function (this: HTMLDialogElement) { this.removeAttribute('open') }
})

const project = { id: 'p1', name: 'Shop' } as never
const render = (role: string, onShare?: () => void) => {
  auth.role = role
  return mount(createElement(ShellV2, { project, section: 'model', problems: { model: 2 }, onShare, children: createElement('p', null, 'child') } as never))
}
const openPalette = async (host: HTMLElement) => {
  const b = [...host.querySelectorAll('button')].find((x) => /Search or jump/.test(x.textContent ?? ''))!
  await act(async () => { b.click() }); await flush()
  return [...document.querySelectorAll('[role=option]')].map((o) => o.firstElementChild?.textContent)
}

describe('ShellV2', () => {
  it('renders every rail group, the current page and the problem badge', async () => {
    const host = await render('customer')
    for (const g of RAIL_GROUPS) expect(host.querySelector(`[data-rail-group="${g.id}"]`)).not.toBeNull()
    expect(host.querySelector('a[aria-current=page]')?.textContent).toContain('2')
    expect(host.textContent).toContain('child')
  })

  it('hides Admin for a customer, in the bar and in the palette', async () => {
    const host = await render('customer')
    expect([...host.querySelectorAll('a')].some((a) => a.textContent === 'Admin')).toBe(false)
    expect(await openPalette(host)).not.toContain('Admin console')
  })

  it('shows Admin and the share command for staff when onShare is given', async () => {
    const host = await render('admin', () => {})
    expect([...host.querySelectorAll('a')].some((a) => a.textContent === 'Admin')).toBe(true)
    const labels = await openPalette(host)
    expect(labels).toContain('Admin console')
    expect(labels).toContain('Share project')
    expect(labels).toContain('Sign out')
  })

  it('omits the share command without onShare', async () => {
    const host = await render('customer')
    expect(await openPalette(host)).not.toContain('Share project')
  })
})
