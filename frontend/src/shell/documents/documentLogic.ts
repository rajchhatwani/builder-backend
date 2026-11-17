/** Pure helpers for the document review queue (D34, packs.ai.documents). Confidence is integer basis points; text offsets are untrusted. */
export type Anchor = { page: number; start: number; end: number; quote: string }
export type DocField = { name: string; value: string | null; confidence_bp: number; anchor: Anchor | null; corrected: boolean; original_value: string | null; review_required: boolean }
export type DocStatus = 'needs_review' | 'extracted' | 'approved' | 'rejected'
export type Doc = {
  id: string; kind: string; title: string; status: DocStatus | string; call_id?: string | null; fields: DocField[]; reject_reason?: string | null
  reviewed_by?: string | null; reviewed_at?: string | null; created_at?: string; updated_at?: string; content?: string | null
}
export const STATUSES: DocStatus[] = ['needs_review', 'extracted', 'approved', 'rejected']
export const STATUS_LABEL: Record<string, string> = { needs_review: 'Needs review', extracted: 'Extracted', approved: 'Approved', rejected: 'Rejected' }
export const DEFAULT_REVIEW_BELOW_BP = 8000

export const isReviewable = (status: string) => status === 'needs_review' || status === 'extracted'
export const isStatus = (s: string): s is DocStatus => (STATUSES as string[]).includes(s)

/** 9200 -> "92%", 9250 -> "92.5%". Non-integers and out-of-range values are clamped, never NaN. */
export function confidencePercent(bp: number): string {
  const n = Number.isFinite(bp) ? Math.min(10000, Math.max(0, Math.round(bp))) : 0
  const whole = Math.floor(n / 100), frac = n % 100
  if (frac === 0) return `${whole}%`
  return `${whole}.${String(frac).padStart(2, '0').replace(/0$/, '')}%`
}
export const isLowConfidence = (f: Pick<DocField, 'confidence_bp' | 'review_required' | 'value'>, threshold = DEFAULT_REVIEW_BELOW_BP) =>
  f.review_required || f.value === null || !(f.confidence_bp >= threshold)

export type Segment = { text: string; field?: string }
export type Highlighted = { segments: Segment[]; fallbacks: { field: string; quote: string; found: boolean }[] }

/** Is the anchor a usable range of `content` whose slice equals the quote? */
export function anchorValid(a: Anchor | null | undefined, content: string): boolean {
  return !!a && Number.isInteger(a.start) && Number.isInteger(a.end) && a.start >= 0 && a.end > a.start && a.end <= content.length && content.slice(a.start, a.end) === a.quote
}

/** Splits the text into plain and highlighted segments. Overlapping or invalid anchors never throw: a bad anchor falls back to a quote
 *  search (first occurrence) and, failing that, is listed under `fallbacks` with found=false so the UI can still show the quote. */
export function highlightSegments(content: string, fields: DocField[]): Highlighted {
  const ranges: { start: number; end: number; field: string }[] = []
  const fallbacks: Highlighted['fallbacks'] = []
  for (const f of fields) {
    const a = f.anchor
    if (!a) continue
    let r: { start: number; end: number } | null = null
    if (anchorValid(a, content)) r = { start: a.start, end: a.end }
    else if (typeof a.quote === 'string' && a.quote.length > 0) {
      const i = content.indexOf(a.quote)
      if (i >= 0) r = { start: i, end: i + a.quote.length }
      fallbacks.push({ field: f.name, quote: a.quote, found: i >= 0 })
    } else fallbacks.push({ field: f.name, quote: '', found: false })
    if (r) ranges.push({ ...r, field: f.name })
  }
  ranges.sort((x, y) => x.start - y.start || y.end - x.end)
  const segments: Segment[] = []
  let pos = 0
  for (const r of ranges) {
    if (r.start < pos) continue // overlapping range: the earlier field keeps the text
    if (r.start > pos) segments.push({ text: content.slice(pos, r.start) })
    segments.push({ text: content.slice(r.start, r.end), field: r.field })
    pos = r.end
  }
  if (pos < content.length) segments.push({ text: content.slice(pos) })
  return { segments, fallbacks }
}

export function documentErrorMessage(status: number, body: unknown): string {
  const b = (typeof body === 'object' && body !== null ? body : {}) as { code?: unknown; message?: unknown; details?: unknown }
  const code = typeof b.code === 'string' ? b.code : ''
  switch (code) {
    case 'review_pending': return 'Some flagged fields have not been corrected yet. Correct them, or acknowledge them to approve as they are.'
    case 'self_review_forbidden': return 'You uploaded this document, so someone else must review it (self review is switched off in the spec).'
    case 'retry_with_new_key': return 'The earlier upload with that key left no document. Upload again with a new idempotency key.'
    case 'document_closed': return 'This document was already approved or rejected and can no longer change.'
    case 'unknown_field': return 'That field does not exist on this document.'
    case 'missing_required_fields': {
      const names = Array.isArray(b.details) ? b.details.flatMap((d) => (typeof d === 'string' ? [d] : typeof d === 'object' && d && typeof (d as { name?: unknown }).name === 'string' ? [(d as { name: string }).name] : typeof d === 'object' && d && typeof (d as { field?: unknown }).field === 'string' ? [(d as { field: string }).field] : [])) : []
      return `Required fields are still empty${names.length ? `: ${names.join(', ')}` : ''}. Correct them, then approve.`
    }
    case 'budget_exceeded': return 'The AI budget for this period is used up.'
  }
  if (status === 401) return 'The token was not accepted (missing, wrong or expired).'
  if (status === 403 && code !== 'forbidden' && code) return (typeof b.message === 'string' && b.message) || 'You may not do this.'
  if (status === 403) return 'Your role may not review documents (the spec lists review roles).'
  if (status === 404) return 'That document or field no longer exists.'
  if (status === 409) return 'This document was already approved or rejected and can no longer change.'
  return (typeof b.message === 'string' && b.message) || `The document API answered ${status}.`
}

export const pageOffset = (page: number, limit: number) => Math.max(0, page) * limit
export function pageInfo(total: number, limit: number, offset: number): { from: number; to: number; hasPrev: boolean; hasNext: boolean } {
  if (total <= 0) return { from: 0, to: 0, hasPrev: false, hasNext: false }
  return { from: offset + 1, to: Math.min(total, offset + limit), hasPrev: offset > 0, hasNext: offset + limit < total }
}
/** Roving focus over a vertical list. */
export function moveRow(len: number, cur: number, key: string): number {
  if (len <= 0) return 0
  if (key === 'ArrowDown') return Math.min(len - 1, cur + 1)
  if (key === 'ArrowUp') return Math.max(0, cur - 1)
  if (key === 'Home') return 0
  if (key === 'End') return len - 1
  return cur
}
export function parseDocJson(text: string): unknown { return JSON.parse(text) }

/** Field names from a 409 review_pending answer (`details: [{name}]`); anything else yields []. */
export function pendingFields(body: unknown): string[] {
  const b = (typeof body === 'object' && body !== null ? body : {}) as { code?: unknown; details?: unknown }
  if (b.code !== 'review_pending' || !Array.isArray(b.details)) return []
  return b.details.flatMap((d) => (typeof d === 'object' && d && typeof (d as { name?: unknown }).name === 'string' ? [(d as { name: string }).name] : typeof d === 'string' ? [d] : []))
}
