import { describe, expect, it } from 'vitest'
import { getBlock, removeBlock, setBlock } from './packsLogic'

const PACKS = { money: { ledger: { max_entries: 5 }, currency: { currencies: ['USD'] } }, booking: { kinds: [] }, ai: { x: 1 } }

describe('packsLogic', () => {
  it('reads a block, and null when off', () => {
    expect(getBlock(PACKS, 'money', 'ledger')).toEqual({ max_entries: 5 })
    expect(getBlock(PACKS, 'money', 'invoicing')).toBeNull()
    expect(getBlock({}, 'booking')).toBeNull()
    expect(getBlock(null, 'money', 'ledger')).toBeNull()
    expect(getBlock(PACKS, 'booking')).toEqual({ kinds: [] })
  })
  it('sets one block and keeps everything else', () => {
    const next = setBlock(PACKS, 'money', 'ledger', { max_entries: 9 })
    expect(next).toEqual({ ...PACKS, money: { ledger: { max_entries: 9 }, currency: { currencies: ['USD'] } } })
    expect(PACKS.money.ledger.max_entries).toBe(5)
    expect(setBlock(null, 'money', 'ledger', { a: 1 })).toEqual({ money: { ledger: { a: 1 } } })
    expect(setBlock(PACKS, 'booking', undefined, { kinds: [1] })).toEqual({ ...PACKS, booking: { kinds: [1] } })
  })
  it('removes a block, and a pack left empty', () => {
    expect(removeBlock(PACKS, 'money', 'ledger')).toEqual({ ...PACKS, money: { currency: { currencies: ['USD'] } } })
    expect(removeBlock({ money: { ledger: {} }, ai: {} }, 'money', 'ledger')).toEqual({ ai: {} })
    expect(removeBlock(PACKS, 'booking')).toEqual({ money: PACKS.money, ai: PACKS.ai })
  })
})
