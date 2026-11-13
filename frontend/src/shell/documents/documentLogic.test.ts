import { describe, expect, it } from 'vitest'
import { anchorValid, confidencePercent, documentErrorMessage, highlightSegments, isLowConfidence, isReviewable, moveRow, pageInfo, pendingFields, type DocField } from './documentLogic'

const f = (o: Partial<DocField>): DocField => ({ name: 'total', value: '1', confidence_bp: 9000, anchor: null, corrected: false, original_value: null, review_required: false, ...o })

describe('confidence', () => {
  it('formats basis points as percent', () => {
    expect(confidencePercent(9200)).toBe('92%'); expect(confidencePercent(9250)).toBe('92.5%'); expect(confidencePercent(9205)).toBe('92.05%')
    expect(confidencePercent(0)).toBe('0%'); expect(confidencePercent(10000)).toBe('100%'); expect(confidencePercent(99999)).toBe('100%'); expect(confidencePercent(NaN)).toBe('0%')
  })
  it('flags low confidence below the threshold, missing values and server review flags', () => {
    expect(isLowConfidence(f({ confidence_bp: 7999 }))).toBe(true)
    expect(isLowConfidence(f({ confidence_bp: 8000 }))).toBe(false)
    expect(isLowConfidence(f({ confidence_bp: 9900, review_required: true }))).toBe(true)
    expect(isLowConfidence(f({ value: null, confidence_bp: 10000 }))).toBe(true)
    expect(isLowConfidence(f({ confidence_bp: 9000 }), 9500)).toBe(true)
  })
})

describe('anchors and highlights', () => {
  const text = 'Total: 1250.00 EUR from Acme'
  it('validates anchors against the text', () => {
    expect(anchorValid({ page: 1, start: 7, end: 14, quote: '1250.00' }, text)).toBe(true)
    expect(anchorValid({ page: 1, start: 7, end: 99, quote: '1250.00' }, text)).toBe(false)
    expect(anchorValid({ page: 1, start: 8, end: 15, quote: '1250.00' }, text)).toBe(false)
    expect(anchorValid({ page: 1, start: -1, end: 3, quote: 'x' }, text)).toBe(false)
    expect(anchorValid(null, text)).toBe(false)
  })
  it('splits text into segments around valid anchors', () => {
    const h = highlightSegments(text, [f({ anchor: { page: 1, start: 7, end: 14, quote: '1250.00' } })])
    expect(h.segments.map((s) => s.text).join('')).toBe(text)
    expect(h.segments.find((s) => s.field)?.text).toBe('1250.00'); expect(h.fallbacks).toEqual([])
  })
  it('falls back to quote search for out-of-range offsets, lists unfound quotes, never throws', () => {
    const h = highlightSegments(text, [
      f({ name: 'a', anchor: { page: 1, start: 500, end: 507, quote: '1250.00' } }),
      f({ name: 'b', anchor: { page: 1, start: 0, end: 5, quote: 'Nowhere' } }),
      f({ name: 'c', anchor: { page: 1, start: 3, end: 1, quote: '' } }),
    ])
    expect(h.segments.find((s) => s.field === 'a')?.text).toBe('1250.00')
    expect(h.fallbacks).toEqual([{ field: 'a', quote: '1250.00', found: true }, { field: 'b', quote: 'Nowhere', found: false }, { field: 'c', quote: '', found: false }])
    expect(h.segments.map((s) => s.text).join('')).toBe(text)
  })
  it('drops overlapping ranges and handles empty text', () => {
    const h = highlightSegments(text, [f({ name: 'a', anchor: { page: 1, start: 7, end: 14, quote: '1250.00' } }), f({ name: 'b', anchor: { page: 1, start: 10, end: 14, quote: '50.00' } })])
    expect(h.segments.filter((s) => s.field)).toHaveLength(1)
    expect(highlightSegments('', [f({ anchor: { page: 1, start: 0, end: 1, quote: 'x' } })]).segments).toEqual([])
  })
})

describe('messages and helpers', () => {
  it('maps errors', () => {
    expect(documentErrorMessage(409, { code: 'document_closed' })).toMatch(/already approved or rejected/)
    expect(documentErrorMessage(409, {})).toMatch(/already approved or rejected/)
    expect(documentErrorMessage(403, {})).toMatch(/review roles/)
    expect(documentErrorMessage(404, {})).toMatch(/no longer exists/)
    expect(documentErrorMessage(422, { code: 'missing_required_fields', details: [{ name: 'total' }, 'vendor'] })).toMatch(/total, vendor/)
    expect(documentErrorMessage(500, { message: 'boom' })).toBe('boom')
    expect(documentErrorMessage(500, null)).toMatch(/500/)
  })
  it('maps new codes and extracts pending fields', () => {
    expect(documentErrorMessage(403, { code: 'self_review_forbidden' })).toMatch(/someone else/)
    expect(documentErrorMessage(409, { code: 'retry_with_new_key' })).toMatch(/new idempotency key/)
    expect(documentErrorMessage(409, { code: 'review_pending' })).toMatch(/acknowledge/)
    expect(pendingFields({ code: 'review_pending', details: [{ name: 'a' }, 'b', 3] })).toEqual(['a', 'b'])
    expect(pendingFields({ code: 'document_closed', details: [{ name: 'a' }] })).toEqual([]); expect(pendingFields(null)).toEqual([])
  })
  it('reviewable statuses', () => { expect(isReviewable('needs_review')).toBe(true); expect(isReviewable('extracted')).toBe(true); expect(isReviewable('approved')).toBe(false); expect(isReviewable('rejected')).toBe(false) })
  it('paging and roving focus', () => {
    expect(pageInfo(0, 20, 0)).toEqual({ from: 0, to: 0, hasPrev: false, hasNext: false })
    expect(pageInfo(45, 20, 20)).toEqual({ from: 21, to: 40, hasPrev: true, hasNext: true })
    expect(pageInfo(45, 20, 40)).toEqual({ from: 41, to: 45, hasPrev: true, hasNext: false })
    expect(moveRow(3, 0, 'ArrowDown')).toBe(1); expect(moveRow(3, 2, 'ArrowDown')).toBe(2); expect(moveRow(3, 0, 'ArrowUp')).toBe(0)
    expect(moveRow(3, 1, 'End')).toBe(2); expect(moveRow(3, 1, 'Home')).toBe(0); expect(moveRow(0, 0, 'End')).toBe(0)
  })
})
