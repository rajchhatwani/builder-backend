import { describe, expect, it } from 'vitest'
import type { ExpressionField, StateMachineBody } from '../../api/types'
import { applyCompletion, errorSegments, guardsOf, mapLimit, moveActive, prefixAt, suggest, typeLabel } from './rulesLogic'

const FIELDS: ExpressionField[] = [
  { name: 'status', type: 'string', nullable: false },
  { name: 'amount', type: 'decimal', nullable: false },
  { name: 'po_amount', type: 'decimal', nullable: true },
  { name: 'Archived', type: 'bool', nullable: false },
]

describe('identifier prefix and suggestions', () => {
  it('finds the identifier right before the caret', () => {
    expect(prefixAt('amount > 1 and sta', 18)).toEqual({ start: 15, prefix: 'sta' })
    expect(prefixAt('amount', 3)).toEqual({ start: 0, prefix: 'amo' })
    expect(prefixAt('amount > ', 9)).toEqual({ start: 9, prefix: '' })
  })

  it('a name glued to a number or a dot is not a prefix', () => {
    expect(prefixAt('12ab', 4).prefix).toBe('')
    expect(prefixAt('a.b', 3).prefix).toBe('')
    expect(prefixAt('_x1', 3).prefix).toBe('_x1')
  })

  it('suggests fields by case-insensitive prefix, sorted; nothing without a prefix unless forced', () => {
    expect(suggest(FIELDS, 'a').map((f) => f.name)).toEqual(['amount', 'Archived'])
    expect(suggest(FIELDS, 'zz')).toEqual([])
    expect(suggest(FIELDS, '')).toEqual([])
    expect(suggest(FIELDS, '', true)).toHaveLength(4)
    expect(suggest(FIELDS, 'status')).toEqual([]) // already typed in full
    expect(suggest(FIELDS, 'amount')).toEqual([]) // the only match is exactly what is typed
    expect(suggest(FIELDS, 'po_').map((f) => f.name)).toEqual(['po_amount'])
  })

  it('inserts a completion in place of the prefix and puts the caret after it', () => {
    expect(applyCompletion('amount > 1 and sta', 15, 18, 'status')).toEqual({ text: 'amount > 1 and status', caret: 21 })
    expect(applyCompletion('am > 1', 0, 2, 'amount')).toEqual({ text: 'amount > 1', caret: 6 })
  })

  it('wraps around in the list', () => {
    expect(moveActive(0, -1, 3)).toBe(2)
    expect(moveActive(2, 1, 3)).toBe(0)
    expect(moveActive(0, 1, 0)).toBe(-1)
  })
})

describe('error position', () => {
  it('marks the whole identifier at the position', () => {
    expect(errorSegments('bogus_field > 1', 0)).toEqual({ before: '', mark: 'bogus_field', after: ' > 1', atEnd: false })
    expect(errorSegments('a + zz9 and b', 4)).toEqual({ before: 'a + ', mark: 'zz9', after: ' and b', atEnd: false })
  })
  it('marks one character for punctuation', () => {
    expect(errorSegments('a ) b', 2)).toEqual({ before: 'a ', mark: ')', after: ' b', atEnd: false })
  })
  it('an error past the end shows an end marker', () => {
    expect(errorSegments('amount <= ', 10)).toEqual({ before: 'amount <= ', mark: '', after: '', atEnd: true })
    expect(errorSegments('', 0).atEnd).toBe(true)
  })
})

describe('labels and guards', () => {
  it('names the type', () => {
    expect(typeLabel('bool')).toBe('true/false expression')
    expect(typeLabel('decimal')).toBe('decimal expression')
    expect(typeLabel(null)).toBe('expression')
  })

  it('lists only transitions that have a guard', () => {
    const machines: StateMachineBody[] = [
      { entity: 'Invoice', field: 'status', initial: 'draft', transitions: [
        { name: 'submit', from_states: ['draft'], to_state: 'sub' },
        { name: 'auto', from_states: ['sub'], to_state: 'ok', auto: true, when: 'amount < 5' },
      ] },
      { entity: 'Leave', field: 'status', initial: 'new' },
    ]
    expect(guardsOf(machines)).toEqual([{ key: 'Invoice/auto', entity: 'Invoice', transition: 'auto', when: 'amount < 5' }])
  })

  it('mapLimit keeps order and never exceeds the limit', async () => {
    let inflight = 0
    let peak = 0
    const out = await mapLimit([1, 2, 3, 4, 5, 6], 2, async (n) => {
      inflight++
      peak = Math.max(peak, inflight)
      await new Promise((r) => setTimeout(r, 5))
      inflight--
      return n * 2
    })
    expect(out).toEqual([2, 4, 6, 8, 10, 12])
    expect(peak).toBeLessThanOrEqual(2)
  })
})
