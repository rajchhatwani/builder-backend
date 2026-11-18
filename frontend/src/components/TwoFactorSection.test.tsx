import { createElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { byText, click, mount, setInput } from '../shell/ai/testUtils'
import { TwoFactorSection } from './TwoFactorSection'

const m = vi.hoisted(() => ({ status: vi.fn(), setup: vi.fn(), enable: vi.fn(), disable: vi.fn(), regen: vi.fn(), resume: vi.fn(), setUser: vi.fn() }))
vi.mock('../api/client', async (orig) => ({
  ...(await orig<typeof import('../api/client')>()),
  api: { mfaStatus: m.status, totpSetup: m.setup, totpEnable: m.enable, totpDisable: m.disable, regenerateRecoveryCodes: m.regen, resume: m.resume },
}))
vi.mock('./AuthProvider', () => ({ useAuth: () => ({ setUser: m.setUser }) }))
vi.mock('./Ui', () => ({ useUi: () => ({ confirm: vi.fn(), toast: vi.fn() }) }))

const off = { totp_enabled: false, enabled_at: null, recovery_codes_left: 0, session_mfa: false, required_for_staff: false, required_by: [], sso_only: false }
const on = { ...off, totp_enabled: true, session_mfa: true, recovery_codes_left: 8 }

beforeEach(() => {
  for (const f of Object.values(m)) f.mockReset()
  m.resume.mockResolvedValue(null)
})

const submit = (host: HTMLElement) => click(host.querySelector('form button[type="submit"]'))

describe('TwoFactorSection', () => {
  it('turn on: password -> scan -> recovery codes', async () => {
    m.status.mockResolvedValue(off)
    m.setup.mockResolvedValue({ secret: 'ABCD', otpauth_uri: 'otpauth://totp/x?secret=ABCD' })
    m.enable.mockResolvedValue({ user: { id: 'u' }, recovery_codes: ['aaaa-1111', 'bbbb-2222'] })
    const host = await mount(createElement(TwoFactorSection))
    await click(byText(host, 'button', /^Turn on$/)!)
    await setInput(host.querySelector('input[type="password"]') as HTMLInputElement, 'pw')
    await submit(host)
    expect(m.setup).toHaveBeenCalledWith('pw')
    await setInput(host.querySelector('input[autocomplete="one-time-code"]') as HTMLInputElement, ' 123456 ')
    await submit(host)
    expect(m.enable).toHaveBeenCalledWith('123456')
    expect(m.setUser).toHaveBeenCalledWith({ id: 'u' })
    expect(host.textContent).toContain('aaaa-1111')
  })

  it('wrong password shows the friendly message and stays on the step', async () => {
    m.status.mockResolvedValue(off)
    m.setup.mockRejectedValue(new ApiError(401, { code: 'invalid_password', message: 'x', details: [] }))
    const host = await mount(createElement(TwoFactorSection))
    await click(byText(host, 'button', /^Turn on$/)!)
    await setInput(host.querySelector('input[type="password"]') as HTMLInputElement, 'bad')
    await submit(host)
    expect(host.textContent).toContain("That password isn't right.")
    expect(host.querySelector('input[type="password"]')).toBeTruthy()
  })

  it('regenerate: bad code shows the code message and clears the field', async () => {
    m.status.mockResolvedValue(on)
    m.regen.mockRejectedValue(new ApiError(400, { code: 'invalid_mfa_code', message: 'x', details: [] }))
    const host = await mount(createElement(TwoFactorSection))
    await click(byText(host, 'button', /New recovery codes/)!)
    const input = host.querySelector('input[autocomplete="one-time-code"]') as HTMLInputElement
    await setInput(input, '000000')
    await submit(host)
    expect(host.textContent).toContain("That code didn't work")
    expect((host.querySelector('input[autocomplete="one-time-code"]') as HTMLInputElement).value).toBe('')
  })

  it('hides Turn off while an organization requires two-factor', async () => {
    m.status.mockResolvedValue({ ...on, required_by: [{ organization_id: 'o', slug: 'o', name: 'Acme' }] })
    const host = await mount(createElement(TwoFactorSection))
    expect(byText(host, 'button', /Turn off/)).toBeUndefined()
    expect(host.textContent).toContain('Acme')
  })
})
