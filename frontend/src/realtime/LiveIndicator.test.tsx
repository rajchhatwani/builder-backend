import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import { LiveView, alsoHereText, othersHere } from './LiveIndicator'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const U = (id: string, display: string) => ({ user_id: id, display, where: 'model' })
let host: HTMLElement | null = null
afterEach(() => { host?.remove(); host = null })

async function render(props: Parameters<typeof LiveView>[0]) {
  host = document.createElement('div'); document.body.appendChild(host)
  await act(async () => { createRoot(host!).render(createElement(LiveView, props)) })
  return host
}

describe('live indicator', () => {
  it('excludes self and summarises long rosters', () => {
    expect(othersHere([U('a', 'Me'), U('b', 'Maya')], 'a')).toEqual([U('b', 'Maya')])
    expect(alsoHereText([])).toBe('')
    expect(alsoHereText([U('1', 'A'), U('2', 'B'), U('3', 'C'), U('4', 'D'), U('5', 'E')])).toBe('Also here: A, B, C +2')
  })
  it('renders status as text and a polite live roster', async () => {
    const el = await render({ status: 'live', users: [U('a', 'Me'), U('b', 'Maya')], selfId: 'a' })
    expect(el.querySelector('[data-testid=live-status]')?.textContent).toBe('Live')
    const here = el.querySelector('[data-testid=also-here]')!
    expect(here.textContent).toBe('Also here: Maya')
    expect(here.getAttribute('aria-live')).toBe('polite')
  })
  it('keeps the roster element mounted when empty and says Reconnecting…', async () => {
    const el = await render({ status: 'reconnecting', users: [], selfId: 'a' })
    expect(el.querySelector('[data-testid=live-status]')?.textContent).toBe('Reconnecting…')
    expect(el.querySelector('[data-testid=also-here]')?.textContent).toBe('')
  })
})
