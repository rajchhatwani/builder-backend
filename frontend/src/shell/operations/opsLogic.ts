/** Pure logic of the operations dashboards (places, geofences, matching, prediction, routing). The generated API speaks
 *  integer micro-degrees; the UI shows decimal degrees. Only integer maths is used for coordinates. */
import { formatMicro, type Geofence, type Place, type Pt } from '../map/mapLogic'

export { formatMicro }
export type { Geofence, Place, Pt }
export const LAT_DEG = 90
export const LNG_DEG = 180

/** A coordinate the user is typing, in decimal degrees. "40", "40.", "-0.5", ".25" parse; "-", "", "1e3", "1,5" and more than
 *  six decimals do not. Returns micro-degrees or null (also when beyond `limitDeg`). */
export function parseDegrees(text: string, limitDeg: number): number | null {
  const m = text.trim().match(/^(-?)(\d*)(?:\.(\d*))?$/)
  if (!m) return null
  const [, sign, whole, frac = ''] = m
  if ((whole === '' && frac === '') || frac.length > 6) return null
  const micro = Number(whole || '0') * 1_000_000 + Number(frac.padEnd(6, '0'))
  if (!Number.isSafeInteger(micro) || micro > limitDeg * 1_000_000) return null
  return sign ? -micro : micro
}
export const parseLat = (t: string) => parseDegrees(t, LAT_DEG)
export const parseLng = (t: string) => parseDegrees(t, LNG_DEG)

/** Micro-degrees as the shortest decimal-degree text ("40.5", "-74", "0.000001"); null -> "". */
export function degText(micro: number | null): string {
  if (micro === null || !Number.isInteger(micro)) return ''
  const s = formatMicro(micro).replace(/0+$/, '')
  return s.endsWith('.') ? s.slice(0, -1) : s
}

/** A whole number typed by the user (no sign unless `min` < 0, no decimals); null when malformed or out of range. */
export function parseWhole(text: string, min: number, max: number): number | null {
  if (!/^-?\d{1,16}$/.test(text.trim())) return null
  const n = Number(text.trim())
  return Number.isSafeInteger(n) && n >= min && n <= max ? n : null
}
export const wholeText = (n: number | null) => (n === null ? '' : String(n))

export interface LL { lat: number | null; lng: number | null }
export const EMPTY_LL: LL = { lat: null, lng: null }
export const llComplete = (p: LL): p is Pt & { lat: number; lng: number } => p.lat !== null && p.lng !== null
export const toPt = (p: LL): Pt | null => (p.lat !== null && p.lng !== null ? { lat_micro: p.lat, lng_micro: p.lng } : null)
export const fromPt = (p: Pt | null | undefined): LL => (p ? { lat: p.lat_micro, lng: p.lng_micro } : EMPTY_LL)
export const pointQuery = (p: Pt) => `lat_micro=${p.lat_micro}&lng_micro=${p.lng_micro}`

// ── Places ────────────────────────────────────────────────────────────────
export interface PlaceDraft { id: string | null; name: string; kind: string; ll: LL }
export const EMPTY_PLACE: PlaceDraft = { id: null, name: '', kind: '', ll: EMPTY_LL }
export const placeDraft = (p: Place): PlaceDraft => ({ id: p.id, name: p.name, kind: p.kind ?? '', ll: { lat: p.lat_micro, lng: p.lng_micro } })
export type Built<T> = { ok: true; body: T } | { ok: false; error: string }

export function placeBody(d: PlaceDraft): Built<{ name: string; kind: string | null; lat_micro: number; lng_micro: number }> {
  const name = d.name.trim(), kind = d.kind.trim()
  if (!name) return { ok: false, error: 'Give the place a name.' }
  if (name.length > 200) return { ok: false, error: 'The name is at most 200 characters.' }
  if (kind.length > 32) return { ok: false, error: 'The kind is at most 32 characters.' }
  if (!llComplete(d.ll)) return { ok: false, error: 'Latitude (-90 to 90) and longitude (-180 to 180) are required, in decimal degrees with at most six decimals.' }
  return { ok: true, body: { name, kind: kind || null, lat_micro: d.ll.lat, lng_micro: d.ll.lng } }
}

// ── Geofences ─────────────────────────────────────────────────────────────
export interface FenceDraft { id: string | null; name: string; shape: 'circle' | 'polygon'; center: LL; radius: number | null; vertices: LL[] }
export const EMPTY_FENCE: FenceDraft = { id: null, name: '', shape: 'circle', center: EMPTY_LL, radius: null, vertices: [EMPTY_LL, EMPTY_LL, EMPTY_LL] }
export const fenceDraft = (g: Geofence): FenceDraft => ({
  id: g.id, name: g.name, shape: g.shape, center: fromPt(g.center), radius: g.radius_m,
  vertices: g.vertices && g.vertices.length ? g.vertices.map(fromPt) : EMPTY_FENCE.vertices,
})
export const addVertex = (v: LL[]): LL[] => [...v, EMPTY_LL]
export const removeVertex = (v: LL[], i: number): LL[] => v.filter((_, j) => j !== i)
export const setVertex = (v: LL[], i: number, p: LL): LL[] => v.map((x, j) => (j === i ? p : x))
export const moveVertex = (v: LL[], i: number, by: -1 | 1): LL[] => {
  const j = i + by
  if (j < 0 || j >= v.length) return v
  const out = [...v]; [out[i], out[j]] = [out[j], out[i]]
  return out
}

export type FenceBody = { name: string; shape: 'circle'; center: Pt; radius_m: number } | { name: string; shape: 'polygon'; vertices: Pt[] }
export function fenceBody(d: FenceDraft): Built<FenceBody> {
  const name = d.name.trim()
  if (!name) return { ok: false, error: 'Give the geofence a name.' }
  if (name.length > 200) return { ok: false, error: 'The name is at most 200 characters.' }
  if (d.shape === 'circle') {
    const c = toPt(d.center)
    if (!c) return { ok: false, error: 'A circle needs a centre latitude and longitude.' }
    if (d.radius === null || d.radius < 1) return { ok: false, error: 'The radius is a whole number of metres, at least 1.' }
    return { ok: true, body: { name, shape: 'circle', center: c, radius_m: d.radius } }
  }
  if (d.vertices.length < 3) return { ok: false, error: 'A polygon needs at least 3 vertices.' }
  const pts = d.vertices.map(toPt)
  const bad = pts.findIndex((p) => p === null)
  if (bad >= 0) return { ok: false, error: `Vertex ${bad + 1} needs a latitude and a longitude.` }
  return { ok: true, body: { name, shape: 'polygon', vertices: pts as Pt[] } }
}

// ── Matching ──────────────────────────────────────────────────────────────
export interface CandidateBody { id: string; lat_micro?: number; lng_micro?: number; load?: number; rating_milli?: number }
const splitLines = (t: string) => t.split('\n').map((l) => l.trim()).filter((l) => l && !l.startsWith('#'))
const cells = (l: string) => l.split(/[,;\t]/).map((c) => c.trim())

/** One candidate per line: `id, lat, lng, load, rating_milli`. lat and lng go together; load (>=0) and rating (0-5000) are optional. */
export function parseCandidates(text: string): { ok: true; items: CandidateBody[] } | { ok: false; error: string } {
  const lines = splitLines(text)
  if (lines.length === 0) return { ok: false, error: 'Add at least one candidate, one per line: id, lat, lng, load, rating.' }
  const items: CandidateBody[] = []
  const seen = new Set<string>()
  for (const [i, line] of lines.entries()) {
    const [id, la = '', ln = '', load = '', rating = ''] = cells(line)
    const at = `Candidate line ${i + 1}`
    if (!id || id.length > 128) return { ok: false, error: `${at}: the id is 1-128 characters.` }
    if (seen.has(id)) return { ok: false, error: `${at}: the id ${id} is listed twice.` }
    seen.add(id)
    const c: CandidateBody = { id }
    if (la || ln) {
      const lat = parseLat(la), lng = parseLng(ln)
      if (lat === null || lng === null) return { ok: false, error: `${at}: latitude and longitude must both be valid decimal degrees.` }
      c.lat_micro = lat; c.lng_micro = lng
    }
    if (load) { const n = parseWhole(load, 0, 1_000_000_000); if (n === null) return { ok: false, error: `${at}: load is a whole number, 0 or more.` }; c.load = n }
    if (rating) { const n = parseWhole(rating, 0, 5000); if (n === null) return { ok: false, error: `${at}: rating is a whole number from 0 to 5000 (thousandths of a star).` }; c.rating_milli = n }
    items.push(c)
  }
  return { ok: true, items }
}

/** One request per line: `request_ref, lat, lng`. */
export function parseBatchRequests(text: string): { ok: true; items: { request_ref: string; point: Pt }[] } | { ok: false; error: string } {
  const lines = splitLines(text)
  if (lines.length === 0) return { ok: false, error: 'Add at least one request, one per line: ref, lat, lng.' }
  const items: { request_ref: string; point: Pt }[] = []
  const seen = new Set<string>()
  for (const [i, line] of lines.entries()) {
    const [ref, la = '', ln = ''] = cells(line)
    const at = `Request line ${i + 1}`
    if (!ref || ref.length > 128) return { ok: false, error: `${at}: the reference is 1-128 characters.` }
    if (seen.has(ref)) return { ok: false, error: `${at}: the reference ${ref} is listed twice.` }
    seen.add(ref)
    const lat = parseLat(la), lng = parseLng(ln)
    if (lat === null || lng === null) return { ok: false, error: `${at}: latitude and longitude must be valid decimal degrees.` }
    items.push({ request_ref: ref, point: { lat_micro: lat, lng_micro: lng } })
  }
  return { ok: true, items }
}

export const MATCH_STATES = ['offered', 'accepted', 'rejected', 'expired'] as const
export const STATE_LABEL: Record<string, string> = { offered: 'Offered', accepted: 'Accepted', rejected: 'Rejected', expired: 'Expired' }

// ── Prediction ────────────────────────────────────────────────────────────
/** Features, one `name = value` per line. Whole numbers become integers, true/false booleans, anything else text. */
export function parseFeatures(text: string): { ok: true; features: Record<string, number | string | boolean> } | { ok: false; error: string } {
  const out: Record<string, number | string | boolean> = {}
  for (const [i, line] of splitLines(text).entries()) {
    const eq = line.indexOf('=')
    const key = (eq < 0 ? line : line.slice(0, eq)).trim()
    const raw = eq < 0 ? '' : line.slice(eq + 1).trim()
    if (eq < 0 || !key || key.length > 64) return { ok: false, error: `Feature line ${i + 1}: write name = value (name is 1-64 characters).` }
    if (key in out) return { ok: false, error: `Feature line ${i + 1}: ${key} is listed twice.` }
    if (raw === 'true' || raw === 'false') out[key] = raw === 'true'
    else if (/^-?\d+$/.test(raw)) {
      const n = Number(raw)
      if (!Number.isSafeInteger(n) || Math.abs(n) > 2 ** 53) return { ok: false, error: `Feature line ${i + 1}: a whole number is within +-2^53.` }
      out[key] = n
    } else if (raw.length > 256) return { ok: false, error: `Feature line ${i + 1}: text is at most 256 characters.` }
    else out[key] = raw
  }
  if (Object.keys(out).length > 100) return { ok: false, error: 'At most 100 features.' }
  return { ok: true, features: out }
}

/** thousandths -> "1.500"; null -> "n/a". */
export function formatMilli(milli: number | null): string {
  if (milli === null) return 'n/a'
  const neg = milli < 0, a = Math.abs(milli)
  return `${neg ? '-' : ''}${Math.floor(a / 1000)}.${String(a % 1000).padStart(3, '0')}`
}
/** basis points -> "85.25%"; null -> "n/a". */
export function formatBp(bp: number | null): string {
  if (bp === null) return 'n/a'
  const neg = bp < 0, a = Math.abs(bp)
  return `${neg ? '-' : ''}${Math.floor(a / 100)}.${String(a % 100).padStart(2, '0')}%`
}
export const parseKind = (t: string): boolean => /^[A-Za-z0-9][A-Za-z0-9._:-]{0,31}$/.test(t.trim())

// ── Routing ───────────────────────────────────────────────────────────────
export function formatDistance(m: number): string {
  return m < 1000 ? `${m} m` : `${Math.floor(m / 1000)}.${String(m % 1000).padStart(3, '0').slice(0, 2)} km`
}
export function formatDuration(s: number): string {
  const h = Math.floor(s / 3600), min = Math.floor((s % 3600) / 60), sec = s % 60
  return h ? `${h} h ${min} min` : min ? `${min} min ${sec} s` : `${sec} s`
}
/** `datetime-local` text ("2026-01-01T09:30") to an ISO instant; '' -> null (no departure given); invalid -> undefined. */
export function departIso(text: string): string | null | undefined {
  if (!text.trim()) return null
  const t = Date.parse(text)
  return Number.isFinite(t) ? new Date(t).toISOString() : undefined
}

// ── Errors ────────────────────────────────────────────────────────────────
/** A clear message for an error answer of the generated project. `what` names the block ("geo", "matching"...). */
export function opsErrorMessage(status: number, body: unknown, what: string): string {
  const b = (body && typeof body === 'object' ? body : {}) as { code?: unknown; message?: unknown; detail?: unknown }
  const code = typeof b.code === 'string' ? b.code : ''
  const message = typeof b.message === 'string' ? b.message : ''
  if (status === 403) return `The generated project refused this (403): your role is not in the ${what} block's read or write roles. Ask an admin to change the roles in the ${what} settings.`
  if (status === 401) return 'Your session was not accepted (401). Sign in again.'
  if (status === 404 && !code) return `This project has no ${what} API (404). Enable the ${what} block of the operations pack in the spec to use this page.`
  if (status === 404) return message || 'That item no longer exists.'
  if (status === 409) return message || 'That conflicts with the current state (for example the assignment was already decided).'
  if (status === 429) return 'Too many requests (429). Wait a moment and try again.'
  if (code === 'invalid_coordinates') return 'A coordinate is outside the valid range (latitude -90 to 90, longitude -180 to 180).'
  if (message) return message
  if (status === 422 && Array.isArray(b.detail)) {
    const first = b.detail[0] as { msg?: unknown } | undefined
    if (first && typeof first.msg === 'string') return first.msg
  }
  if (status === 422) return 'The API rejected the input (422).'
  return `The ${what} API answered ${status}.`
}
