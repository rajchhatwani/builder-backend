import axe from 'axe-core'
import { createElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { click, mount, q, setInput } from '../ai/testUtils'
import { PreviewSessionGate } from './PreviewSessionGate'
import { stubSession } from './testSession'
import type { PreviewSession, SessionStatus } from './previewSession'

const gate = (s: PreviewSession) => createElement(PreviewSessionGate, { session: s, prefix: 'x', children: createElement('p', { 'data-testid': 'kid' }, 'child') })
const inputs = () => ({ email: q('preview-email') as HTMLInputElement, pass: q('preview-password') as HTMLInputElement })

describe('PreviewSessionGate', () => {
  it('renders children only when ready', async () => {
    await mount(gate(stubSession('ready')))
    expect(q('kid')).not.toBeNull()
  })
  it.each<SessionStatus>(['no-origin', 'loading', 'starting', 'no-preview', 'error', 'needs-signin'])('hides children for %s', async (s) => {
    await mount(gate(stubSession(s)))
    expect(q('kid')).toBeNull()
  })
  it('explains a missing origin', async () => {
    const host = await mount(gate(stubSession('no-origin')))
    expect(q('x-no-origin')).not.toBeNull()
    expect(host.textContent).toMatch(/VITE_PREVIEW_API_ORIGIN/)
  })
  it('shows status text while loading and starting', async () => {
    let host = await mount(gate(stubSession('loading')))
    expect(q('preview-session-wait')?.textContent).toMatch(/Looking for a preview/)
    host = await mount(gate(stubSession('starting', { previewState: 'starting' })))
    expect(host.textContent).toMatch(/preview is starting/)
  })
  it('offers a Start button when there is no preview', async () => {
    const start = vi.fn(async () => {})
    await mount(gate(stubSession('no-preview', { start })))
    await click(q('preview-start'))
    expect(start).toHaveBeenCalledTimes(1)
  })
  it('shows the error as an alert with a retry', async () => {
    const start = vi.fn(async () => {})
    await mount(gate(stubSession('error', { error: 'boom', start })))
    expect(q('preview-session-error')?.querySelector('[role=alert]')?.textContent).toBe('boom')
    await click(q('preview-retry'))
    expect(start).toHaveBeenCalledTimes(1)
  })
  it('uses a default error text', async () => {
    const host = await mount(gate(stubSession('error')))
    expect(host.querySelector('[role=alert]')?.textContent).toMatch(/could not be set up/)
  })

  it('disables Sign in until email and password are filled, then signs in with the trimmed email', async () => {
    const signIn = vi.fn(async () => null)
    await mount(gate(stubSession('needs-signin', { signIn })))
    const btn = q('preview-signin-btn') as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    await setInput(inputs().email, '  me@x.test  ')
    expect(btn.disabled).toBe(true)
    await setInput(inputs().pass, 'secret')
    expect(btn.disabled).toBe(false)
    await click(btn)
    expect(signIn).toHaveBeenCalledWith('me@x.test', 'secret')
    expect(inputs().pass.value).toBe('')
    expect(q('preview-signin-error')).toBeNull()
  })
  it('shows the returned message and keeps the password on failure', async () => {
    const signIn = vi.fn(async () => 'Wrong password')
    await mount(gate(stubSession('needs-signin', { signIn })))
    await setInput(inputs().email, 'a@b.c'); await setInput(inputs().pass, 'pw')
    await click(q('preview-signin-btn'))
    expect(q('preview-signin-error')?.textContent).toBe('Wrong password')
    expect(inputs().pass.value).toBe('pw')
  })
  it('Create test account needs a password of at least 8 characters', async () => {
    const register = vi.fn(async () => null)
    await mount(gate(stubSession('needs-signin', { register })))
    const btn = q('preview-register') as HTMLButtonElement
    await setInput(inputs().email, 'a@b.c'); await setInput(inputs().pass, '1234567')
    expect(btn.disabled).toBe(true)
    await setInput(inputs().pass, '12345678')
    expect(btn.disabled).toBe(false)
    await click(btn)
    expect(register).toHaveBeenCalledWith('a@b.c', '12345678')
  })
  it('mentions a sleeping preview', async () => {
    const host = await mount(gate(stubSession('needs-signin', { previewState: 'sleeping' })))
    expect(host.textContent).toMatch(/asleep/)
  })

  it.each<SessionStatus>(['no-origin', 'loading', 'no-preview', 'error', 'needs-signin'])('has no axe violations for %s', async (s) => {
    const host = await mount(gate(stubSession(s, { error: 'x' })))
    const res = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res.violations.map((v) => v.id)).toEqual([])
  })
})
