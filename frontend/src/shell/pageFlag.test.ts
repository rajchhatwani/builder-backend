import { afterEach, describe, expect, it } from 'vitest'
import { pageFlagOn, setPageFlag } from './pageFlag'

afterEach(() => { localStorage.clear(); window.history.replaceState(null, '', '/') })

describe('page flags', () => {
  it('are on by default', () => {
    expect(pageFlagOn('payments')).toBe(true)
  })
  it('?ui.payments=classic turns one page off (persisted, others untouched); v2 turns it on again', () => {
    window.history.replaceState(null, '', '/?ui.payments=classic')
    expect(pageFlagOn('payments')).toBe(false)
    window.history.replaceState(null, '', '/')
    expect(pageFlagOn('payments')).toBe(false) // persisted
    expect(pageFlagOn('storage')).toBe(true)
    window.history.replaceState(null, '', '/?ui.payments=v2')
    expect(pageFlagOn('payments')).toBe(true)
  })
  it('v1 also means classic; other values are ignored; setPageFlag round-trips', () => {
    window.history.replaceState(null, '', '/?ui.deployment=v1')
    expect(pageFlagOn('deployment')).toBe(false)
    window.history.replaceState(null, '', '/?ui.storage=nonsense')
    expect(pageFlagOn('storage')).toBe(true)
    setPageFlag('deployment', 'v2')
    expect(pageFlagOn('deployment')).toBe(true)
    setPageFlag('deployment', 'classic')
    expect(pageFlagOn('deployment')).toBe(false)
  })
})
