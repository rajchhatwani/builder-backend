import { describe, expect, it } from 'vitest'
import { EXAMPLE_TRACE, MAX_SPANS, formatMs, linkPath, linksOf, parseTrace, type TraceSpan } from './traceLogic'

const span = (id: string, parent: string | null, start: number, end: number, extra: Partial<TraceSpan> = {}) => ({
  span_id: id, parent_span_id: parent, name: `n-${id}`, service: 'api', start_unix_ms: start, end_unix_ms: end, status: 'ok', attributes: {}, ...extra,
})
const doc = (spans: unknown[]) => JSON.stringify({ trace_id: 't', spans })
const ok = (text: string) => { const r = parseTrace(text); if (!r.ok) throw new Error(r.error); return r.trace }
const err = (text: string) => { const r = parseTrace(text); if (r.ok) throw new Error('expected failure'); return r.error }

describe('parseTrace', () => {
  it('lays out the example: depth, offsets and percentages', () => {
    const t = ok(JSON.stringify(EXAMPLE_TRACE))
    expect(t.rows).toHaveLength(7)
    expect(t.rows.map((r) => r.depth)).toEqual([0, 1, 1, 1, 2, 2, 1])
    expect(t.totalMs).toBe(182)
    expect(t.rows[0]).toMatchObject({ offsetPct: 0, widthPct: 100 })
    expect(t.rows[3].span.span_id).toBe('s4')
    expect(t.rows[3].offsetPct).toBeCloseTo((33 / 182) * 100)
    expect(t.warnings).toEqual([])
  })
  it('marks the longest child chain as the critical path', () => {
    const t = ok(JSON.stringify(EXAMPLE_TRACE))
    expect(t.rows.filter((r) => r.onCriticalPath).map((r) => r.span.span_id)).toEqual(['s1', 's4', 's6'])
  })
  it('rejects empty, oversized, bad JSON and wrong shapes with a sentence', () => {
    expect(err('  ')).toMatch(/Paste a trace/)
    expect(err('{nope')).toMatch(/not valid JSON/)
    expect(err('[]')).toMatch(/JSON object/)
    expect(err(JSON.stringify({ spans: [] }))).toMatch(/trace_id/)
    expect(err(JSON.stringify({ trace_id: 't' }))).toMatch(/spans list/)
    expect(err(doc([]))).toMatch(/no spans/)
    expect(err('x'.repeat(2 * 1024 * 1024 + 1))).toMatch(/larger than 2 MB/)
  })
  it('caps the span count', () => {
    const many = Array.from({ length: MAX_SPANS + 1 }, (_, i) => span(`s${i}`, null, 0, 1))
    expect(err(doc(many))).toMatch(/limit is 5000/)
    expect(ok(doc(many.slice(0, MAX_SPANS))).rows).toHaveLength(MAX_SPANS)
  })
  it('rejects malformed spans and duplicate ids', () => {
    expect(err(doc([span('a', null, 0, 1, { status: 'bad' as never })]))).toMatch(/status/)
    expect(err(doc([{ ...span('a', null, 0, 1), start_unix_ms: 'x' }]))).toMatch(/numeric/)
    expect(err(doc([span('a', null, 0, 1), span('a', null, 0, 1)]))).toMatch(/more than once/)
    expect(err(doc([5]))).toMatch(/not an object/)
  })
  it('shows a span with a missing parent as a root with a warning', () => {
    const t = ok(doc([span('a', null, 0, 10), span('b', 'ghost', 2, 4)]))
    expect(t.rows.map((r) => r.depth)).toEqual([0, 0])
    expect(t.warnings.join(' ')).toMatch(/not in the trace/)
  })
  it('breaks parent cycles and self-parents without hanging', () => {
    const t = ok(doc([span('a', 'b', 0, 10), span('b', 'a', 1, 5), span('c', 'c', 2, 3)]))
    expect(t.rows).toHaveLength(3)
    expect(t.warnings.some((w) => /loop/.test(w))).toBe(true)
    expect(t.warnings.some((w) => /own parent/.test(w))).toBe(true)
  })
  it('clamps end before start and keeps bars visible', () => {
    const t = ok(doc([span('a', null, 0, 100), span('b', 'a', 50, 40)]))
    const b = t.rows.find((r) => r.span.span_id === 'b')!
    expect(b.durationMs).toBe(0)
    expect(b.widthPct).toBeGreaterThanOrEqual(0.5)
    expect(t.warnings.join(' ')).toMatch(/ended before it started/)
  })
  it('handles a zero-length trace and a very deep chain', () => {
    expect(ok(doc([span('a', null, 5, 5)])).rows[0].widthPct).toBeGreaterThan(0)
    const chain = Array.from({ length: 3000 }, (_, i) => span(`s${i}`, i ? `s${i - 1}` : null, i, 4000 - i))
    expect(ok(doc(chain)).rows[2999].depth).toBe(2999)
  })
  it('does not let a __proto__ attribute reach the prototype', () => {
    const t = ok('{"trace_id":"t","spans":[{"span_id":"a","parent_span_id":null,"name":"n","start_unix_ms":0,"end_unix_ms":1,"status":"ok","attributes":{"__proto__":"x","k":1,"o":{"z":1}}}]}')
    const attrs = t.rows[0].span.attributes
    expect(Object.getPrototypeOf(attrs)).toBe(Object.prototype)
    expect(Object.keys(attrs).sort()).toEqual(['__proto__', 'k'])
  })
})

describe('links', () => {
  it('resolves rule and hook attributes', () => {
    const t = ok(JSON.stringify(EXAMPLE_TRACE))
    expect(linksOf(t.rows[2].span)).toEqual([{ kind: 'rule', name: 'invoice_within_limit' }])
    expect(linksOf(t.rows[3].span)).toEqual([{ kind: 'hook', name: 'check_po_match' }])
    expect(linksOf(t.rows[0].span)).toEqual([])
    expect(linkPath('p1', { kind: 'rule', name: 'x' })).toBe('/p/p1/rules')
    expect(linkPath('p1', { kind: 'hook', name: 'x' })).toBe('/p/p1/hooks')
  })
  it('ignores non-text or blank link attributes', () => {
    expect(linksOf(span('a', null, 0, 1, { attributes: { 'bb.rule': 3, 'bb.hook': ' ' } }) as TraceSpan)).toEqual([])
  })
})

describe('formatMs', () => {
  it('formats ms and seconds', () => {
    expect(formatMs(12)).toBe('12 ms')
    expect(formatMs(12.34)).toBe('12.3 ms')
    expect(formatMs(1500)).toBe('1.5 s')
    expect(formatMs(2000)).toBe('2 s')
  })
})
