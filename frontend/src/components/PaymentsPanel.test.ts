import { describe, expect, it } from 'vitest'
import { withProvider } from './PaymentsPanel'

describe('PaymentsPanel provider switch', () => {
  it('drops currencies Razorpay cannot charge and re-picks the fixed one', () => {
    const f = withProvider({ provider: 'stripe', currencies: ['CHF', 'USD'], currency: 'CHF' }, 'razorpay')
    expect(f.currencies).toEqual(['USD'])
    expect(f.currency).toBe('USD')
  })
  it('keeps an allowed fixed currency', () => {
    expect(withProvider({ currencies: ['EUR'], currency: 'EUR' }, 'razorpay').currency).toBe('EUR')
  })
})
