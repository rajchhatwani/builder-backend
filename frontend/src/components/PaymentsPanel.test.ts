import { describe, expect, it } from 'vitest'
import { toWrite, withProvider } from './PaymentsPanel'

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

describe('PaymentsPanel toWrite payable', () => {
  const base = {
    provider: 'stripe', entity: 'order', amountField: 'total', statusField: '', currencyMode: 'fixed',
    currency: 'USD', currencyField: '', statusPending: 'a', statusPaid: 'b', statusPartiallyRefunded: 'c',
    statusRefunded: 'd', currencies: ['USD'], maxAmountMinor: '100', successUrls: '', cancelUrls: '', threshold: '', peakPayments: '', peakWebhooks: '', apiReplicas: '', serverWorkers: '', workerReplicas: '', workerConcurrency: '', poolSize: '', webhookMode: '',
  }
  it('keeps a partial payable pick instead of silently dropping it', () => {
    const w = toWrite(base as never)
    expect(w.payable).not.toBeNull()
    expect(w.payable?.entity).toBe('order')
  })
  it('sends null payable only when nothing is chosen', () => {
    expect(toWrite({ ...base, entity: '', amountField: '' } as never).payable).toBeNull()
  })
})
