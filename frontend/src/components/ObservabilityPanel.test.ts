import { describe, expect, it } from 'vitest'
import { recommendedSampleRatio } from './ObservabilityPanel'

describe('recommendedSampleRatio', () => {
  it('follows the typed rps like the server', () => {
    expect(recommendedSampleRatio(null)).toBe(1)
    expect(recommendedSampleRatio(10)).toBe(1)
    expect(recommendedSampleRatio(1000)).toBe(0.05)
    expect(recommendedSampleRatio(1000000)).toBe(0.01)
  })
})
