import { createElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { click, flush, mount, setInput } from '../shell/ai/testUtils'
import { RolesPanel } from './RolesPanel'

const m = vi.hoisted(() => ({ list: vi.fn(), create: vi.fn(), update: vi.fn(), confirm: vi.fn() }))
vi.mock('../api/client', async (orig) => ({
  ...(await orig<typeof import('../api/client')>()),
  api: { listRoles: m.list, createRole: m.create, updateRole: m.update, deleteRole: vi.fn() },
}))
vi.mock('./Ui', () => ({ useUi: () => ({ confirm: m.confirm, toast: vi.fn() }) }))

const weak = () => new ApiError(409, { code: 'access_weakened', message: 'more access', details: [] })
const role = { id: 'r1', name: 'clerk', label: 'Clerk', is_default: false, self_assignable: false, invite_only: false, inherits_from: null, position: 0 }

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
  for (const f of Object.values(m)) f.mockReset()
  m.list.mockResolvedValue({ items: [role], total: 1 })
  m.confirm.mockResolvedValue(true)
})

const btn = (host: HTMLElement, re: RegExp) => Array.from(host.querySelectorAll('button')).find((b) => re.test(b.textContent ?? ''))!

describe('RolesPanel access_weakened (F-0902)', () => {
  it('create: confirms, then repeats with confirm_weakening', async () => {
    m.create.mockRejectedValueOnce(weak()).mockResolvedValue({})
    const host = await mount(createElement(RolesPanel, { projectId: 'p' }))
    await click(btn(host, /Add role|New role|Create role/i))
    const inputs = host.querySelectorAll('dialog input[type="text"], dialog input:not([type])')
    await setInput(inputs[0] as HTMLInputElement, 'admin2')
    await setInput(inputs[1] as HTMLInputElement, 'Admin 2')
    await click(host.querySelector('dialog button[type="submit"]'))
    await flush()
    expect(m.confirm).toHaveBeenCalledTimes(1)
    expect(m.create.mock.calls.map((c) => c[2])).toEqual([false, true])
  })

  it('edit: declined confirm does not repeat the write', async () => {
    m.update.mockRejectedValueOnce(weak())
    m.confirm.mockResolvedValue(false)
    const host = await mount(createElement(RolesPanel, { projectId: 'p' }))
    await click(btn(host, /Edit/i))
    await click(host.querySelector('dialog button[type="submit"]'))
    await flush()
    expect(m.update).toHaveBeenCalledTimes(1)
  })

  it('edit: confirmed repeat sends confirm', async () => {
    m.update.mockRejectedValueOnce(weak()).mockResolvedValue({})
    const host = await mount(createElement(RolesPanel, { projectId: 'p' }))
    await click(btn(host, /Edit/i))
    await click(host.querySelector('dialog button[type="submit"]'))
    await flush()
    expect(m.update.mock.calls.map((c) => c[2])).toEqual([false, true])
  })
})
