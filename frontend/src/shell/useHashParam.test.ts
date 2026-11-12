import { describe, expect, it } from 'vitest'
import { hashParam, withHashParam } from './useHashParam'

describe('hash params', () => {
  it('reads and writes one param without touching the route', () => {
    expect(hashParam('#/p/1/hooks?hook=check%20po', 'hook')).toBe('check po')
    expect(hashParam('#/p/1/hooks', 'hook')).toBeNull()
    expect(hashParam('#/p/1/hooks?hook=', 'hook')).toBeNull()
    expect(withHashParam('#/p/1/specdiff', 'base', '3')).toBe('#/p/1/specdiff?base=3')
    expect(withHashParam('#/p/1/specdiff?base=3&x=1', 'base', null)).toBe('#/p/1/specdiff?x=1')
    expect(withHashParam('#/p/1/specdiff?base=3', 'base', null)).toBe('#/p/1/specdiff')
  })
})
