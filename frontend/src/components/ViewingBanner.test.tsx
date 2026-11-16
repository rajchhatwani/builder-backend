import { createElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { byText, click, mount } from '../shell/ai/testUtils'
import { ViewingBanner } from './ViewingBanner'
import { ApiError } from '../api/client'

const m = vi.hoisted(() => ({ toast: vi.fn(), end: vi.fn(), setViewing: vi.fn() }))
vi.mock('../api/client', async (orig) => ({ ...(await orig<typeof import('../api/client')>()), api: { endImpersonation: m.end } }))
vi.mock('./Ui', () => ({ useUi: () => ({ toast: m.toast }) }))
vi.mock('./AuthProvider', () => ({
  useAuth: () => ({ viewing: { user_email: 'u@x.y', organization_name: 'O', operator_email: 'op@x.y', expires_at: new Date(Date.now() + 600000).toISOString(), writes_allowed: false, writes_until: null }, setViewing: m.setViewing }),
}))

beforeEach(() => { Object.values(m).forEach((f) => f.mockReset()); window.close = vi.fn() })

describe('ViewingBanner exit (F-0567)', () => {
  it('keeps the banner and warns when ending the session failed', async () => {
    m.end.mockRejectedValue(new Error('down'))
    const host = await mount(createElement(ViewingBanner))
    await click(byText(host, 'button', /exit/i)!)
    expect(m.setViewing).not.toHaveBeenCalled()
    expect(m.toast).toHaveBeenCalledWith(expect.stringMatching(/may still be active/), 'danger')
  })
  it('leaves when the session is already gone', async () => {
    m.end.mockRejectedValue(new ApiError(410, { code: 'gone', message: 'gone', details: [] } as never))
    const host = await mount(createElement(ViewingBanner))
    await click(byText(host, 'button', /exit/i)!)
    expect(m.setViewing).toHaveBeenCalledWith(null)
  })
})
