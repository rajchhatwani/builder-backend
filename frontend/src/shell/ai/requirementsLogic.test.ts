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
  it('accepts docx and xlsx like the server', () => {
    const r = checkFiles([{ name: 'a.docx', size: 10 }, { name: 'b.XLSX', size: 10 }])
    expect(r.ok).toEqual([0, 1])
    expect(r.errors).toHaveLength(0)
  })
  it('mirrors server limits: 5 files, 5 MB each, 12 MB total, counting earlier picks', () => {
    const f = (n: string, size = 10) => ({ name: n, size })
    expect(checkFiles([1, 2, 3, 4, 5, 6].map((n) => f(`${n}.txt`))).ok).toHaveLength(5)
    expect(checkFiles([f('a.pdf', 6 * 1024 * 1024)]).errors).toHaveLength(1)
    const mb = 1024 * 1024
    expect(checkFiles([f('a.pdf', 5 * mb), f('b.pdf', 5 * mb), f('c.pdf', 3 * mb)]).ok).toEqual([0, 1])
    expect(checkFiles([f('x.txt')], [f('1.txt'), f('2.txt'), f('3.txt'), f('4.txt'), f('5.txt')]).ok).toEqual([])
  })
})
