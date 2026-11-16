import { createElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { click, mount, setInput } from '../shell/ai/testUtils'
import { MembersDialog } from './MembersDialog'

const m = vi.hoisted(() => ({ list: vi.fn(), add: vi.fn() }))
vi.mock('../api/client', async (orig) => ({
  ...(await orig<typeof import('../api/client')>()),
  api: { listMembers: m.list, addMember: m.add },
}))
vi.mock('./AuthProvider', () => ({ useUser: () => ({ id: 'u1' }) }))
vi.mock('./Ui', () => ({ useUi: () => ({ confirm: vi.fn(), toast: vi.fn() }) }))

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
  m.list.mockReset(); m.add.mockReset()
  m.list.mockResolvedValue([{ user_id: 'u1', email: 'me@example.com', role: 'owner', mcp_enabled: false }])
})

const mountDialog = () => mount(createElement(MembersDialog, { open: true, projectId: 'p', projectName: 'P', onClose: () => {} }))

describe('MembersDialog add', () => {
  it('keeps the typed email when adding fails', async () => {
    m.add.mockRejectedValue(new Error('no such user'))
    const host = await mountDialog()
    const input = host.querySelector('input[type="email"]') as HTMLInputElement
    await setInput(input, 'typo@example.com')
    await click(host.querySelector('button[type="submit"]'))
    expect(m.add).toHaveBeenCalled()
    expect((host.querySelector('input[type="email"]') as HTMLInputElement).value).toBe('typo@example.com')
  })

  it('clears the email after success', async () => {
    m.add.mockResolvedValue({})
    const host = await mountDialog()
    await setInput(host.querySelector('input[type="email"]') as HTMLInputElement, 'ok@example.com')
    await click(host.querySelector('button[type="submit"]'))
    expect((host.querySelector('input[type="email"]') as HTMLInputElement).value).toBe('')
  })
})
