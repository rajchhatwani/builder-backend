import { createElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { click, mount, q, setInput } from '../../shell/ai/testUtils'
import { SsoDomainsPage } from './SsoDomainsPage'

const m = vi.hoisted(() => ({ release: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({ ...(await orig<typeof import('../../api/client')>()), api: { adminReleaseSsoDomain: m.release } }))
beforeEach(() => m.release.mockReset())

async function fill(domain = ' Example.COM ', reason = 'customer asked') {
  await setInput(q('sso-domain') as HTMLInputElement, domain)
  await setInput(q('sso-reason') as HTMLInputElement, reason)
}

describe('SsoDomainsPage', () => {
  it('needs a domain and a reason, then a confirm step before calling the API', async () => {
    m.release.mockResolvedValue({ id: 'o', name: 'Acme' })
    await mount(createElement(SsoDomainsPage, { readOnly: false }))
    expect((q('sso-release') as HTMLButtonElement).disabled).toBe(true)
    await fill()
    await click(q('sso-release'))
    expect(m.release).not.toHaveBeenCalled()
    expect(q('sso-confirm')?.textContent).toContain('example.com')
    await click(q('sso-confirm-confirm'))
    expect(m.release).toHaveBeenCalledWith('example.com', 'customer asked')
    expect(q('sso-done')?.textContent).toContain('Acme')
  })

  it('Cancel releases nothing; a refusal is shown', async () => {
    m.release.mockRejectedValueOnce(new Error('domain not claimed'))
    await mount(createElement(SsoDomainsPage, { readOnly: false }))
    await fill()
    await click(q('sso-release'))
    await click(q('sso-confirm-cancel'))
    expect(m.release).not.toHaveBeenCalled()
    await click(q('sso-release'))
    await click(q('sso-confirm-confirm'))
    expect(q('sso-error')?.textContent).toBe('domain not claimed')
  })

  it('is closed to read-only staff', async () => {
    await mount(createElement(SsoDomainsPage, { readOnly: true }))
    expect(q('sso-readonly')).not.toBeNull()
    expect(q('sso-domain')).toBeNull()
  })
})
