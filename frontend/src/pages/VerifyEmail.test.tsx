import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { CheckInbox } from '../components/CheckInbox'
import { EmailNotVerifiedBanner, isEmailNotVerified } from '../components/EmailNotVerifiedBanner'
import { VerifyEmailPage } from './VerifyEmailPage'

const m = vi.hoisted(() => ({ verifyEmail: vi.fn(), resendVerification: vi.fn(), me: vi.fn() }))
vi.mock('../api/client', async (orig) => ({ ...(await orig<typeof import('../api/client')>()), api: m }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
async function mount(el: ReturnType<typeof createElement>) {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => { root!.render(el) })
  await act(async () => { await Promise.resolve() })
}
const q = (id: string) => host.querySelector<HTMLElement>(`[data-testid=${id}]`)
const apiErr = (status: number, code: string) => new ApiError(status, { code, message: code, details: [] })

beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }) })
afterEach(() => {
  act(() => root?.unmount()); host?.remove(); root = null
  Object.values(m).forEach((f) => f.mockReset())
  vi.useRealTimers()
  window.location.hash = ''
})

describe('VerifyEmailPage', () => {
  it('posts the token once, strips it from the address, and offers sign-in', async () => {
    window.location.hash = '#/verify-email?token=abcdefghij123'
    m.verifyEmail.mockResolvedValue({})
    await mount(createElement(VerifyEmailPage))
    expect(m.verifyEmail).toHaveBeenCalledTimes(1)
    expect(m.verifyEmail).toHaveBeenCalledWith('abcdefghij123')
    expect(window.location.hash).toBe('#/verify-email')
    expect(window.location.href).not.toContain('abcdefghij123')
    expect(q('verify-ok')).not.toBeNull()
    expect(q('verify-signin')?.getAttribute('href')).toBe('#/')
  })

  it('shows an error and a resend option for a bad token', async () => {
    window.location.hash = '#/verify-email?token=badbadbadbad'
    m.verifyEmail.mockRejectedValue(apiErr(400, 'invalid_token'))
    await mount(createElement(VerifyEmailPage))
    expect(q('verify-bad')?.textContent).toContain('not valid any more')
    expect(host.textContent).not.toContain('badbadbadbad')
    expect(q('resend')).toBeNull() // asks for the address first
    const input = host.querySelector<HTMLInputElement>('input[type=email]')!
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'a@b.co')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    m.resendVerification.mockResolvedValue({ status: 'verification_sent', message: 'sent' })
    await act(async () => { q('resend')!.click() })
    expect(m.resendVerification).toHaveBeenCalledWith('a@b.co')
    expect(q('resend-note')?.textContent).toBe('sent')
  })

  it('a link without a token is an error and posts nothing', async () => {
    window.location.hash = '#/verify-email'
    await mount(createElement(VerifyEmailPage))
    expect(m.verifyEmail).not.toHaveBeenCalled()
    expect(q('verify-bad')).not.toBeNull()
  })
})

describe('resend cooldown', () => {
  it('check-inbox starts cooling, re-enables after 60 s, and cools again after a resend', async () => {
    m.resendVerification.mockResolvedValue({ status: 'verification_sent', message: 'sent again' })
    await mount(createElement(CheckInbox, { email: 'a@b.co', message: 'Check your inbox.', onBack: vi.fn() }))
    expect(host.textContent).toContain('a@b.co')
    expect((q('resend') as HTMLButtonElement).disabled).toBe(true)
    for (let i = 0; i < 60; i++) await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect((q('resend') as HTMLButtonElement).disabled).toBe(false)
    await act(async () => { q('resend')!.click() })
    expect(m.resendVerification).toHaveBeenCalledWith('a@b.co')
    expect((q('resend') as HTMLButtonElement).disabled).toBe(true)
    expect(q('resend-note')?.textContent).toBe('sent again')
  })
})

describe('email_not_verified banner', () => {
  it('recognises only 403 email_not_verified', () => {
    expect(isEmailNotVerified(apiErr(403, 'email_not_verified'))).toBe(true)
    expect(isEmailNotVerified(apiErr(403, 'forbidden'))).toBe(false)
    expect(isEmailNotVerified(new Error('x'))).toBe(false)
  })
  it('offers a resend to the signed-in address', async () => {
    m.me.mockResolvedValue({ email: 'me@b.co' })
    m.resendVerification.mockResolvedValue({ status: 'verification_sent', message: 'sent' })
    await mount(createElement(EmailNotVerifiedBanner))
    expect(q('email-not-verified')?.textContent).toContain('Confirm your e-mail')
    await act(async () => { q('resend')!.click() })
    expect(m.resendVerification).toHaveBeenCalledWith('me@b.co')
  })
})
