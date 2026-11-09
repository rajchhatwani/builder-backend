/** F4-5: pure logic for the trace waterfall. The platform stores no traces; the page works on a trace
 *  document the user loads. Everything here is defensive because the input is untrusted text. */

export type AttrValue = string | number | boolean
export interface TraceSpan {
  span_id: string
  parent_span_id: string | null
  name: string
  service: string
  start_unix_ms: number
  end_unix_ms: number
  status: 'ok' | 'error'
  attributes: Record<string, AttrValue>
}
export interface TraceDoc {
  trace_id: string
  spans: TraceSpan[]
}

export const MAX_TRACE_BYTES = 2 * 1024 * 1024
export const MAX_SPANS = 5000

export interface WaterfallRow {
  span: TraceSpan
  depth: number
  /** Start offset from the start of the trace, in ms. */
  offsetMs: number
  durationMs: number
  offsetPct: number
  widthPct: number
  onCriticalPath: boolean
  childCount: number
}
export interface ParsedTrace {
  traceId: string
  rows: WaterfallRow[]
  totalMs: number
  warnings: string[]
}
export type ParseResult = { ok: true; trace: ParsedTrace } | { ok: false; error: string }

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const isStr = (v: unknown): v is string => typeof v === 'string'

/** Validates one raw span. Returns the span or a sentence naming what is wrong. */
function readSpan(raw: unknown, at: number): TraceSpan | string {
  const n = `Span ${at + 1}`
  if (!isRecord(raw)) return `${n} is not an object.`
  if (!isStr(raw.span_id) || !raw.span_id) return `${n} has no span_id.`
  if (!isStr(raw.name) || !raw.name) return `${n} has no name.`
  const parent = raw.parent_span_id
  if (parent !== null && parent !== undefined && !isStr(parent)) return `${n} has a parent_span_id that is not text or null.`
  const start = raw.start_unix_ms
  const end = raw.end_unix_ms
  if (typeof start !== 'number' || !Number.isFinite(start) || typeof end !== 'number' || !Number.isFinite(end)) {
    return `${n} needs numeric start_unix_ms and end_unix_ms.`
  }
  if (raw.status !== 'ok' && raw.status !== 'error') return `${n} status must be "ok" or "error".`
  if (raw.service !== undefined && !isStr(raw.service)) return `${n} has a service that is not text.`
  const entries: [string, AttrValue][] = []
  if (isRecord(raw.attributes)) {
    for (const [k, v] of Object.entries(raw.attributes)) {
      if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') entries.push([k, v])
    }
  } else if (raw.attributes !== undefined) {
    return `${n} attributes must be an object.`
  }
  return {
    span_id: raw.span_id,
    parent_span_id: parent ?? null,
    name: raw.name,
    service: isStr(raw.service) ? raw.service : '',
    start_unix_ms: start,
    end_unix_ms: end,
    status: raw.status,
    attributes: Object.fromEntries(entries), // defines own keys, so a "__proto__" key cannot reach the prototype
  }
}

/** Parses and validates a trace document, then lays it out as waterfall rows. Never throws. */
export function parseTrace(text: string): ParseResult {
  if (!text.trim()) return { ok: false, error: 'Paste a trace document or choose a file first.' }
  if (new TextEncoder().encode(text).length > MAX_TRACE_BYTES) {
    return { ok: false, error: `This trace is larger than ${MAX_TRACE_BYTES / (1024 * 1024)} MB. Trim it and try again.` }
  }
  let doc: unknown
  try {
    doc = JSON.parse(text)
  } catch {
    return { ok: false, error: 'This is not valid JSON. Check for a missing bracket, comma or quote.' }
  }
  if (!isRecord(doc)) return { ok: false, error: 'A trace document is a JSON object with trace_id and spans.' }
  if (!isStr(doc.trace_id) || !doc.trace_id) return { ok: false, error: 'The trace has no trace_id.' }
  if (!Array.isArray(doc.spans)) return { ok: false, error: 'The trace has no spans list.' }
  if (doc.spans.length === 0) return { ok: false, error: 'The trace has no spans.' }
  if (doc.spans.length > MAX_SPANS) return { ok: false, error: `The trace has ${doc.spans.length} spans; the limit is ${MAX_SPANS}.` }

  const warnings: string[] = []
  const spans: TraceSpan[] = []
  const seen = new Set<string>()
  for (let i = 0; i < doc.spans.length; i++) {
    const s = readSpan(doc.spans[i], i)
    if (typeof s === 'string') return { ok: false, error: s }
    if (seen.has(s.span_id)) return { ok: false, error: `The span_id "${s.span_id}" appears more than once.` }
    seen.add(s.span_id)
    if (s.end_unix_ms < s.start_unix_ms) {
      warnings.push(`Span "${s.name}" ended before it started; its end was set to its start.`)
      s.end_unix_ms = s.start_unix_ms
    }
    spans.push(s)
  }
  return { ok: true, trace: layout(doc.trace_id, spans, warnings) }
}

/** Builds the tree (iteratively, chains can be thousands deep) and the percentages for each bar. */
export function layout(traceId: string, spans: TraceSpan[], warnings: string[] = []): ParsedTrace {
  const byId = new Map(spans.map((s) => [s.span_id, s]))
  const order = (a: TraceSpan, b: TraceSpan) => a.start_unix_ms - b.start_unix_ms || a.end_unix_ms - b.end_unix_ms || a.span_id.localeCompare(b.span_id)
  const children = new Map<string, TraceSpan[]>()
  const roots: TraceSpan[] = []
  for (const s of spans) {
    const p = s.parent_span_id
    if (p === null) roots.push(s)
    else if (p === s.span_id || !byId.has(p)) {
      if (p !== s.span_id) warnings.push(`Span "${s.name}" points at a parent that is not in the trace; it is shown as a top-level span.`)
      roots.push(s)
    } else children.set(p, [...(children.get(p) ?? []), s])
  }
  roots.sort(order)
  for (const list of children.values()) list.sort(order)
  const selfLoops = spans.filter((s) => s.parent_span_id === s.span_id)
  for (const s of selfLoops) warnings.push(`Span "${s.name}" is its own parent; it is shown as a top-level span.`)

  // Spans never reached from a root sit in a parent cycle: break each cycle at its earliest span.
  const reached = new Set<string>()
  const visit = (start: TraceSpan, into: TraceSpan[]) => {
    const stack = [start]
    while (stack.length) {
      const s = stack.pop()!
      if (reached.has(s.span_id)) continue
      reached.add(s.span_id)
      into.push(s)
      for (const c of children.get(s.span_id) ?? []) stack.push(c)
    }
  }
  const scratch: TraceSpan[] = []
  for (const r of roots) visit(r, scratch)
  const leftover = spans.filter((s) => !reached.has(s.span_id)).sort(order)
  for (const s of leftover) {
    if (reached.has(s.span_id)) continue
    warnings.push(`Span "${s.name}" is part of a parent loop; the loop was cut here and it is shown as a top-level span.`)
    roots.push(s)
    visit(s, scratch)
  }
  roots.sort(order)

  const t0 = Math.min(...spans.map((s) => s.start_unix_ms))
  const t1 = Math.max(...spans.map((s) => s.end_unix_ms))
  const totalMs = Math.max(t1 - t0, 0)
  const scale = totalMs > 0 ? totalMs : 1
  const dur = (s: TraceSpan) => s.end_unix_ms - s.start_unix_ms

  // Critical path: from the longest top-level span, keep following the longest child.
  const critical = new Set<string>()
  const longest = (list: TraceSpan[]) => list.reduce<TraceSpan | null>((best, s) => (best === null || dur(s) > dur(best) ? s : best), null)
  for (let cur = longest(roots); cur; cur = longest((children.get(cur.span_id) ?? []).filter((c) => !critical.has(c.span_id)))) {
    if (critical.has(cur.span_id)) break
    critical.add(cur.span_id)
  }

  const rows: WaterfallRow[] = []
  const placed = new Set<string>()
  const stack: { span: TraceSpan; depth: number }[] = [...roots].reverse().map((span) => ({ span, depth: 0 }))
  while (stack.length) {
    const { span, depth } = stack.pop()!
    if (placed.has(span.span_id)) continue
    placed.add(span.span_id)
    const kids = (children.get(span.span_id) ?? []).filter((c) => !placed.has(c.span_id))
    const offsetMs = span.start_unix_ms - t0
    const d = dur(span)
    rows.push({
      span, depth, offsetMs, durationMs: d,
      offsetPct: Math.min(100, (offsetMs / scale) * 100),
      widthPct: Math.min(100, Math.max((d / scale) * 100, 0.5)),
      onCriticalPath: critical.has(span.span_id),
      childCount: kids.length,
    })
    for (let i = kids.length - 1; i >= 0; i--) stack.push({ span: kids[i], depth: depth + 1 })
  }
  return { traceId, rows, totalMs, warnings }
}

export interface SpanLink {
  kind: 'rule' | 'hook'
  name: string
}

/** Rule and hook links carried by a span's `bb.rule` / `bb.hook` attributes. */
export function linksOf(span: TraceSpan): SpanLink[] {
  const out: SpanLink[] = []
  const rule = span.attributes['bb.rule']
  const hook = span.attributes['bb.hook']
  if (typeof rule === 'string' && rule.trim()) out.push({ kind: 'rule', name: rule })
  if (typeof hook === 'string' && hook.trim()) out.push({ kind: 'hook', name: hook })
  return out
}

/** Neither the Rules nor the Hooks page can select one item, so a link opens the section. */
export function linkPath(projectId: string, l: SpanLink): string {
  return `/p/${projectId}/${l.kind === 'rule' ? 'rules' : 'hooks'}`
}

export function formatMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(ms >= 10_000 ? 1 : 2).replace(/\.?0+$/, '')} s`
  return `${Number.isInteger(ms) ? ms : ms.toFixed(1)} ms`
}

const T0 = 1_760_000_000_000
const sp = (span_id: string, parent: string | null, name: string, service: string, start: number, end: number, attributes: Record<string, AttrValue> = {}, status: 'ok' | 'error' = 'ok'): TraceSpan => ({
  span_id, parent_span_id: parent, name, service, start_unix_ms: T0 + start, end_unix_ms: T0 + end, status, attributes,
})

/** Fixed example: approving an invoice, with a rule check, a hook and database calls. */
export const EXAMPLE_TRACE: TraceDoc = {
  trace_id: 'ex-invoice-approval-0001',
  spans: [
    sp('s1', null, 'POST /invoices/{id}/approve', 'api', 0, 182, { 'http.method': 'POST', 'http.status_code': 200 }),
    sp('s2', 's1', 'db.select invoice', 'postgres', 4, 16, { 'db.statement': 'select * from invoice where id = $1' }),
    sp('s3', 's1', 'rule invoice_within_limit', 'api', 18, 31, { 'bb.rule': 'invoice_within_limit', 'bb.result': true }),
    sp('s4', 's1', 'hook check_po_match', 'hooks', 33, 151, { 'bb.hook': 'check_po_match', 'bb.point': 'Invoice.before_transition' }),
    sp('s5', 's4', 'db.select purchase_order', 'postgres', 40, 62, { 'db.statement': 'select * from purchase_order where id = $1' }),
    sp('s6', 's4', 'http GET erp.example/po-lines', 'hooks', 64, 140, { 'http.method': 'GET', 'http.status_code': 504 }, 'error'),
    sp('s7', 's1', 'db.update invoice', 'postgres', 153, 176, { 'db.statement': 'update invoice set status = $1 where id = $2' }),
  ],
}
