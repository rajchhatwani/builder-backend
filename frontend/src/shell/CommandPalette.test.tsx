import { act, createElement } from 'react'
import { describe, expect, it, vi, beforeAll } from 'vitest'
import { CommandPalette } from './CommandPalette'
import { mount, flush } from './ai/testUtils'

beforeAll(() => {
  const d = HTMLDialogElement.prototype as unknown as { showModal?: () => void; close?: () => void }
  d.showModal ||= function (this: HTMLDialogElement) { this.setAttribute('open', '') }
  d.close ||= function (this: HTMLDialogElement) { this.removeAttribute('open') }
})

const cmds = (run: () => void = () => {}) => [
  { id: 'a', label: 'Alpha', hint: 'Go to', run: vi.fn() },
  { id: 'b', label: 'Beta', hint: 'Go to', run },
  { id: 'c', label: 'Gamma', hint: 'Action', run: vi.fn() },
]
const key = async (el: Element, k: string) => { await act(async () => { el.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true })) }); await flush(2) }

describe('CommandPalette', () => {
  it('ArrowDown + Enter runs the second command and closes', async () => {
    const run = vi.fn(); const onClose = vi.fn()
    const host = await mount(createElement(CommandPalette, { commands: cmds(run), onClose }))
    const input = host.querySelector('input')!
    await key(input, 'ArrowDown')
    expect(host.querySelectorAll('[role=option]')[1].getAttribute('aria-selected')).toBe('true')
    await key(input, 'Enter')
    expect(onClose).toHaveBeenCalled()
    expect(run).toHaveBeenCalledTimes(1)
  })

  it('clamps ArrowUp at the top and ArrowDown at the bottom', async () => {
    const host = await mount(createElement(CommandPalette, { commands: cmds(), onClose: vi.fn() }))
    const input = host.querySelector('input')!
    await key(input, 'ArrowUp')
    expect(host.querySelectorAll('[role=option]')[0].getAttribute('aria-selected')).toBe('true')
    for (let i = 0; i < 6; i++) await key(input, 'ArrowDown')
    expect(host.querySelectorAll('[role=option]')[2].getAttribute('aria-selected')).toBe('true')
  })

  it('filters by typed text and shows No match', async () => {
    const host = await mount(createElement(CommandPalette, { commands: cmds(), onClose: vi.fn() }))
    const input = host.querySelector('input')!
    const type = async (v: string) => { await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, v); input.dispatchEvent(new Event('input', { bubbles: true })) }) }
    await type('gam')
    expect([...host.querySelectorAll('[role=option]')].map((o) => o.textContent)).toEqual(['GammaAction'])
    await type('zzz')
    expect(host.querySelectorAll('[role=option]')).toHaveLength(0)
    expect(host.textContent).toContain('No match')
  })

  it('scrolls the active option into view when moving with the arrows (F-1279)', async () => {
    const spy = vi.fn()
    Element.prototype.scrollIntoView = spy
    const host = await mount(createElement(CommandPalette, { commands: cmds(), onClose: vi.fn() }))
    spy.mockClear()
    await key(host.querySelector('input')!, 'ArrowDown')
    expect(spy).toHaveBeenCalledWith({ block: 'nearest' })
    expect(spy.mock.contexts.at(-1)).toBe(host.querySelectorAll('[role=option]')[1])
  })
})
