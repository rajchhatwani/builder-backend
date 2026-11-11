import { describe, expect, it } from 'vitest'
import { isBuildHash } from './leaveGuard'

describe('isBuildHash', () => {
  it('keeps run switches inside the Build section free', () => {
    expect(isBuildHash('#/p/p1/build?run=abc', 'p1')).toBe(true)
    expect(isBuildHash('#/p/p1/build', 'p1')).toBe(true)
  })
  it('treats any other section or project as leaving', () => {
    expect(isBuildHash('#/p/p1/rules', 'p1')).toBe(false)
    expect(isBuildHash('#/p/p1/buildings', 'p1')).toBe(false)
    expect(isBuildHash('#/p/p2/build', 'p1')).toBe(false)
  })
})
