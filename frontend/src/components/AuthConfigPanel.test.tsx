import { createElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { click, flush, mount } from '../shell/ai/testUtils'
import { ApiError } from '../api/client'
import { AuthConfigPanel } from './AuthConfigPanel'

const m = vi.hoisted(() => ({ get: vi.fn(), update: vi.fn(), confirm: vi.fn() }))
vi.mock('./Ui', () => ({ useUi: () => ({ confirm: m.confirm, toast: vi.fn() }) }))
vi.mock('../api/client', async (orig) => ({
  ...(await orig<typeof import('../api/client')>()),
  api: { getAuthConfig: m.get, updateAuthConfig: m.update },
}))

const cfg = (over: Record<string, unknown> = {}) => ({
  id: 'a', project_id: 'p', enabled: true, provider: 'builtin', token_store: 'db',
  access_token_ttl_minutes: 15, refresh_token_ttl_days: 7, jwt_algorithm: 'HS256',
  email_magic_link_enabled: false, sms_otp_enabled: false, otp_ttl_minutes: 10,
  email_verification_required: true, invite_only: false, multi_tenant: false,
  deletion_mode: 'soft', sms_provider: null, sms_config: null,
  login_rate_limit: '5/15minutes', register_rate_limit: '10/hour', reset_rate_limit: '3/hour',
  security_headers_enabled: true, app_name: null, app_url: null, email_templates: null, suite: null,
  smtp_config: { host: 'smtp.example.com', port: 587, use_tls: true, from_email: 'a@example.com', from_name: 'App' },
  ...over,
})

beforeEach(() => { m.get.mockReset(); m.update.mockReset(); m.confirm.mockReset(); m.confirm.mockResolvedValue(true) })

describe('AuthConfigPanel SMTP', () => {
  it('shows SMTP fields and keeps the saved SMTP when verification is required without magic link', async () => {
    m.get.mockResolvedValue(cfg())
    m.update.mockResolvedValue(cfg())
    const host = await mount(createElement(AuthConfigPanel, { projectId: 'p' }))
    expect(host.textContent).toContain('SMTP host')
    const form = host.querySelector('form') as HTMLFormElement
    const submit = form.querySelector('button[type="submit"]') as HTMLElement
    await click(submit)
    await flush()
    expect(m.update).toHaveBeenCalled()
    expect(m.update.mock.calls[0][1].smtp_config).toMatchObject({ host: 'smtp.example.com' })
  })

  it('keeps SMTP for invite-only too', async () => {
    m.get.mockResolvedValue(cfg({ email_verification_required: false, invite_only: true }))
    m.update.mockResolvedValue(cfg())
    const host = await mount(createElement(AuthConfigPanel, { projectId: 'p' }))
    await click(host.querySelector('form button[type="submit"]'))
    await flush()
    expect(m.update.mock.calls[0][1].smtp_config).toMatchObject({ host: 'smtp.example.com' })
  })
})

describe('AuthConfigPanel access_weakened', () => {
  const weak = () => new ApiError(409, { code: 'access_weakened', message: 'Turning sign-in off makes rules public', details: [] })

  it('confirms, then repeats the save with confirm_weakening', async () => {
    m.get.mockResolvedValue(cfg())
    m.update.mockRejectedValueOnce(weak()).mockResolvedValue(cfg())
    const host = await mount(createElement(AuthConfigPanel, { projectId: 'p' }))
    await click(host.querySelector('form button[type="submit"]'))
    await flush()
    expect(m.confirm).toHaveBeenCalledTimes(1)
    expect(m.update.mock.calls.map((c) => c[2])).toEqual([false, true])
  })

  it('declined confirm does not repeat the save', async () => {
    m.get.mockResolvedValue(cfg())
    m.update.mockRejectedValue(weak())
    m.confirm.mockResolvedValue(false)
    const host = await mount(createElement(AuthConfigPanel, { projectId: 'p' }))
    await click(host.querySelector('form button[type="submit"]'))
    await flush()
    expect(m.update).toHaveBeenCalledTimes(1)
  })
})
