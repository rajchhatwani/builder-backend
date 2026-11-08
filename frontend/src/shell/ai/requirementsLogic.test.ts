import { describe, expect, it } from 'vitest'
import { checkFiles, coverage, groupItems, sourceLabel, startCheck } from './requirementsLogic'
import type { RequirementItem, RequirementsMap } from './types'

const item = (o: Partial<RequirementItem>): RequirementItem => ({ id: 'i', kind: 'rule', text: 't', source_doc: null, source_page: null, source_section: null, status: 'open', covered_by: null, ...o })
const map = (items: RequirementItem[], questions: RequirementsMap['questions'] = []): RequirementsMap => ({ id: 'm', status: 'ready', items, questions, sources: [] })

describe('requirements logic', () => {
  it('groups by kind in a fixed order, unknown kinds last', () => {
    const g = groupItems([item({ id: '1', kind: 'zeta' }), item({ id: '2', kind: 'rule' }), item({ id: '3', kind: 'entity' }), item({ id: '4', kind: 'rule' })])
    expect(g.map((x) => x.kind)).toEqual(['entity', 'rule', 'zeta'])
    expect(g[1].items.map((i) => i.id)).toEqual(['2', '4'])
  })
  it('labels sources as plain text', () => {
    expect(sourceLabel(item({ source_doc: 'a.pdf', source_page: 3, source_section: 'Pay' }))).toBe('a.pdf, page 3, Pay')
    expect(sourceLabel(item({}))).toBe('Your prompt')
  })
  it('computes coverage without out-of-scope items', () => {
    const c = coverage([item({ status: 'covered' }), item({ status: 'open' }), item({ status: 'out_of_scope' })])
    expect(c).toMatchObject({ total: 3, inScope: 2, covered: 1, open: 1, outOfScope: 1, pct: 50 })
    expect(coverage([]).pct).toBe(0)
  })
  it('needs confirmation only while questions are open', () => {
    const q = (state: string, answer: string | null = null) => ({ id: state, text: 'q', assumption: 'a', answer, state })
    expect(startCheck(null).canStart).toBe(false)
    expect(startCheck(map([item({})], [q('open')]))).toMatchObject({ canStart: true, needsConfirm: true, openCount: 1 })
    expect(startCheck(map([item({})], [q('assumed'), q('answered', 'x')])).needsConfirm).toBe(false)
    expect(startCheck(map([item({ status: 'out_of_scope' })])).canStart).toBe(false)
  })
  it('accepts pdf, txt and md only', () => {
    const r = checkFiles([{ name: 'a.PDF', size: 5 }, { name: 'b.exe', size: 5 }, { name: 'c.md', size: 0 }, { name: 'd.txt', size: 30 * 1024 * 1024 }])
    expect(r.ok).toEqual([0])
    expect(r.errors).toHaveLength(3)
  })
})
