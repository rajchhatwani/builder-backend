import { createElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { mount } from './ai/testUtils'
import { ErrorBoundary } from './ErrorBoundary'

function Boom(): never {
  throw new Error('kaboom')
}

describe('ErrorBoundary (F-1223)', () => {
  it('renders a fallback with reload button instead of a blank page', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const host = await mount(createElement(ErrorBoundary, null, createElement(Boom)))
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('kaboom')
    expect(host.querySelector('button')?.textContent).toMatch(/reload/i)
  })
  it('renders children when nothing throws', async () => {
    const host = await mount(createElement(ErrorBoundary, null, createElement('p', null, 'fine')))
    expect(host.textContent).toContain('fine')
  })
})
