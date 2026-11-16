import { createElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { click, flush, mount } from '../shell/ai/testUtils'
import { ApiError } from '../api/client'
import { KeycloakPanel } from './KeycloakPanel'

const m = vi.hoisted(() => ({ get: vi.fn(), list: vi.fn() }))
vi.mock('../api/client', async (orig) => ({
  ...(await orig<typeof import('../api/client')>()),
  api: { getKeycloak: m.get, listProjects: m.list },
}))
vi.mock('./Ui', () => ({ useUi: () => ({ confirm: vi.fn(async () => true), toast: vi.fn() }) }))

beforeEach(() => {
  m.get.mockReset(); m.list.mockReset()
  m.get.mockRejectedValue(new ApiError(404, { detail: 'nf' } as never))
})

const props = { project: { id: 'p', slug: 'p', name: 'P' }, provider: 'keycloak', issues: [], onChanged: vi.fn() } as never

describe('KeycloakPanel shared-mode scan', () => {
  it('does not scan other projects on mount (own mode)', async () => {
    m.list.mockResolvedValue({ items: [] })
    await mount(createElement(KeycloakPanel, props))
    await flush()
    expect(m.list).not.toHaveBeenCalled()
  })
  it('scans lazily on choosing shared mode and survives a listProjects failure', async () => {
    m.list.mockRejectedValue(new Error('boom'))
    const host = await mount(createElement(KeycloakPanel, props))
    await flush()
    const radio = host.querySelector('input[type="radio"][name="mode"]:not(:checked)') as HTMLElement
    await click(radio)
    await flush()
    expect(m.list).toHaveBeenCalledTimes(1)
  })
})
