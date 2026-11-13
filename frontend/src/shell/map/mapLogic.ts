/** Pure logic of the Map view (F5-2). Coordinates are integer micro-degrees (1e-6 degree); display strings are built with
 *  integer maths only. Pixel positions are plain numbers (screen geometry, never shown as coordinates). No antimeridian
 *  crossing is supported in the view: bounds always satisfy minLng <= maxLng. */

export const LAT_LIMIT = 90_000_000
export const LNG_LIMIT = 180_000_000
/** Smallest span the view may have (about 1.1 km), so one point or a zoom-in never collapses to nothing. */
export const MIN_SPAN = 10_000
export const VIEW_W = 1000
export const VIEW_H = 600
const M_PER_DEG_MICRO_NUM = 111_320n // metres per degree; micro-degree maths below keeps everything in BigInt

export interface Pt { lat_micro: number; lng_micro: number }
export interface Bounds { minLat: number; minLng: number; maxLat: number; maxLng: number }
export interface Position extends Pt { subject_id: string; subject_kind: string | null; lat: string; lng: string; seq: number; recorded_at: string; updated_at: string }
export interface Place extends Pt { id: string; name: string; kind: string | null; lat: string; lng: string }
export interface Geofence { id: string; name: string; shape: 'circle' | 'polygon'; center: Pt | null; radius_m: number | null; vertices: Pt[] | null }
export interface Assignment { id: string; request_ref: string; candidate_id: string; status: string; score: number; distance_m: number; expires_at: string }

export const WORLD: Bounds = { minLat: -LAT_LIMIT, minLng: -LNG_LIMIT, maxLat: LAT_LIMIT, maxLng: LNG_LIMIT }

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

/** 12345678 -> "12.345678", -500 -> "-0.000500". Integer maths. */
export function formatMicro(micro: number): string {
  if (!Number.isInteger(micro)) return '0.000000'
  const neg = micro < 0
  const abs = Math.abs(micro)
  return `${neg ? '-' : ''}${Math.floor(abs / 1_000_000)}.${String(abs % 1_000_000).padStart(6, '0')}`
}

export const formatPoint = (p: Pt) => `${formatMicro(p.lat_micro)}, ${formatMicro(p.lng_micro)}`

/** Smallest box around the points plus padding (fraction 1/8 of the span, at least MIN_SPAN each side), clamped to the globe.
 *  Empty set -> null (the caller shows the whole world). A single point -> a box of 2*MIN_SPAN around it. */
export function fitBounds(points: Pt[]): Bounds | null {
  if (points.length === 0) return null
  let minLat = Infinity, maxLat = -Infinity, minLng = Infinity, maxLng = -Infinity
  for (const p of points) {
    minLat = Math.min(minLat, p.lat_micro); maxLat = Math.max(maxLat, p.lat_micro)
    minLng = Math.min(minLng, p.lng_micro); maxLng = Math.max(maxLng, p.lng_micro)
  }
  const padLat = Math.max(MIN_SPAN, Math.floor((maxLat - minLat) / 8))
  const padLng = Math.max(MIN_SPAN, Math.floor((maxLng - minLng) / 8))
  return {
    minLat: clamp(minLat - padLat, -LAT_LIMIT, LAT_LIMIT), maxLat: clamp(maxLat + padLat, -LAT_LIMIT, LAT_LIMIT),
    minLng: clamp(minLng - padLng, -LNG_LIMIT, LNG_LIMIT), maxLng: clamp(maxLng + padLng, -LNG_LIMIT, LNG_LIMIT),
  }
}

/** Zoom by an integer factor numerator/denominator around the centre: zoomBounds(b, 1, 2) halves the span. */
export function zoomBounds(b: Bounds, num: number, den: number): Bounds {
  const cLat = Math.floor((b.minLat + b.maxLat) / 2), cLng = Math.floor((b.minLng + b.maxLng) / 2)
  const hLat = Math.max(MIN_SPAN, Math.floor(((b.maxLat - b.minLat) * num) / den / 2))
  const hLng = Math.max(MIN_SPAN, Math.floor(((b.maxLng - b.minLng) * num) / den / 2))
  return {
    minLat: clamp(cLat - hLat, -LAT_LIMIT, LAT_LIMIT), maxLat: clamp(cLat + hLat, -LAT_LIMIT, LAT_LIMIT),
    minLng: clamp(cLng - hLng, -LNG_LIMIT, LNG_LIMIT), maxLng: clamp(cLng + hLng, -LNG_LIMIT, LNG_LIMIT),
  }
}

/** Query string for GET /location/positions (the contract's four box parameters). */
export const boxQuery = (b: Bounds) => `min_lat_micro=${b.minLat}&min_lng_micro=${b.minLng}&max_lat_micro=${b.maxLat}&max_lng_micro=${b.maxLng}`

export interface Projection {
  bounds: Bounds
  /** Pixels per micro-degree of latitude; longitude uses the same scale times cosKMilli/1000 (equirectangular at the box centre). */
  project: (p: Pt) => { x: number; y: number }
  /** Pixel length of a metre distance (circle radii). */
  metresToPx: (m: number) => number
  inView: (p: Pt) => boolean
}

/** Equirectangular projection fitted into VIEW_W x VIEW_H keeping the aspect ratio (centred). y grows downwards. */
export function makeProjection(bounds: Bounds, w = VIEW_W, h = VIEW_H): Projection {
  const spanLat = Math.max(1, bounds.maxLat - bounds.minLat)
  const spanLng = Math.max(1, bounds.maxLng - bounds.minLng)
  const midLat = (bounds.minLat + bounds.maxLat) / 2 / 1_000_000
  const k = Math.max(0.01, Math.cos((midLat * Math.PI) / 180)) // lng degrees are shorter by cos(lat)
  const sLat = Math.min(h / spanLat, w / (spanLng * k))
  const offX = (w - spanLng * k * sLat) / 2
  const offY = (h - spanLat * sLat) / 2
  const metresPerMicro = Number(M_PER_DEG_MICRO_NUM) / 1_000_000
  return {
    bounds,
    project: (p) => ({ x: offX + (p.lng_micro - bounds.minLng) * k * sLat, y: offY + (bounds.maxLat - p.lat_micro) * sLat }),
    metresToPx: (m) => (m / metresPerMicro) * sLat,
    inView: (p) => p.lat_micro >= bounds.minLat && p.lat_micro <= bounds.maxLat && p.lng_micro >= bounds.minLng && p.lng_micro <= bounds.maxLng,
  }
}

/** Bounds covering points, circle extents and polygon vertices (what "fit to data" should show). */
export function dataPoints(positions: Pt[], places: Pt[], fences: Geofence[]): Pt[] {
  const out: Pt[] = [...positions, ...places]
  for (const g of fences) {
    if (g.shape === 'polygon' && g.vertices) out.push(...g.vertices)
    if (g.shape === 'circle' && g.center && g.radius_m) {
      const d = Math.ceil((g.radius_m * 1_000_000) / Number(M_PER_DEG_MICRO_NUM))
      out.push({ lat_micro: clamp(g.center.lat_micro - d, -LAT_LIMIT, LAT_LIMIT), lng_micro: clamp(g.center.lng_micro - d, -LNG_LIMIT, LNG_LIMIT) })
      out.push({ lat_micro: clamp(g.center.lat_micro + d, -LAT_LIMIT, LAT_LIMIT), lng_micro: clamp(g.center.lng_micro + d, -LNG_LIMIT, LNG_LIMIT) })
    }
  }
  return out
}

/** Display-only containment (the server /geo/contains is authoritative). Polygons: even-odd ray casting in BigInt (products
 *  exceed 2^53). Circles: equirectangular squared distance in BigInt against radius^2. Border counts as inside. */
export function pointInGeofence(p: Pt, g: Geofence): boolean {
  if (g.shape === 'circle') {
    if (!g.center || !g.radius_m || g.radius_m <= 0) return false
    const cosMilli = BigInt(Math.max(1, Math.round(Math.cos(((g.center.lat_micro / 1_000_000) * Math.PI) / 180) * 1000)))
    const dy = BigInt(p.lat_micro - g.center.lat_micro) * M_PER_DEG_MICRO_NUM // metres * 1e6
    const dx = (BigInt(p.lng_micro - g.center.lng_micro) * M_PER_DEG_MICRO_NUM * cosMilli) / 1000n
    const r = BigInt(g.radius_m) * 1_000_000n
    return dx * dx + dy * dy <= r * r
  }
  const v = g.vertices
  if (!v || v.length < 3) return false
  const px = BigInt(p.lng_micro), py = BigInt(p.lat_micro)
  let inside = false
  for (let i = 0, j = v.length - 1; i < v.length; j = i++) {
    const xi = BigInt(v[i].lng_micro), yi = BigInt(v[i].lat_micro), xj = BigInt(v[j].lng_micro), yj = BigInt(v[j].lat_micro)
    // on-edge test (cross product zero and within the segment box) counts as inside
    const cross = (px - xi) * (yj - yi) - (py - yi) * (xj - xi)
    const within = px >= (xi < xj ? xi : xj) && px <= (xi > xj ? xi : xj) && py >= (yi < yj ? yi : yj) && py <= (yi > yj ? yi : yj)
    if (cross === 0n && within) return true
    if ((yi > py) !== (yj > py)) {
      // x of the edge at py compared to px, done with cross-multiplication to stay integral
      const lhs = (px - xi) * (yj - yi)
      const rhs = (xj - xi) * (py - yi)
      if (yj - yi > 0n ? lhs < rhs : lhs > rhs) inside = !inside
    }
  }
  return inside
}

export const geofencesContaining = (p: Pt, fences: Geofence[]) => fences.filter((g) => pointInGeofence(p, g))

export interface Cluster<T> { key: string; x: number; y: number; items: T[] }

/** Grid clustering in pixel space: items in the same cellPx x cellPx cell merge; the cluster sits at the mean of its members. */
export function clusterByGrid<T extends Pt>(items: T[], proj: Projection, cellPx = 40): Cluster<T>[] {
  const cell = Math.max(1, cellPx)
  const cells = new Map<string, { sx: number; sy: number; items: T[] }>()
  for (const it of items) {
    const { x, y } = proj.project(it)
    const key = `${Math.floor(x / cell)}:${Math.floor(y / cell)}`
    const c = cells.get(key) ?? { sx: 0, sy: 0, items: [] }
    c.sx += x; c.sy += y; c.items.push(it)
    cells.set(key, c)
  }
  return Array.from(cells.entries()).map(([key, c]) => ({ key, x: c.sx / c.items.length, y: c.sy / c.items.length, items: c.items }))
}

export type Freshness = 'fresh' | 'aging' | 'stale'
export const FRESH_S = 60
export const STALE_S = 300

/** Whole seconds between a timestamp and now (never negative; unparsable -> Infinity so it renders stale). */
export function ageSeconds(iso: string, nowMs: number): number {
  const t = Date.parse(iso)
  return Number.isFinite(t) ? Math.max(0, Math.floor((nowMs - t) / 1000)) : Infinity
}
export const freshness = (ageS: number): Freshness => (ageS < FRESH_S ? 'fresh' : ageS < STALE_S ? 'aging' : 'stale')
export function formatAge(ageS: number): string {
  if (!Number.isFinite(ageS)) return 'unknown age'
  if (ageS < 60) return `${ageS}s ago`
  if (ageS < 3600) return `${Math.floor(ageS / 60)} min ago`
  if (ageS < 86400) return `${Math.floor(ageS / 3600)} h ago`
  return `${Math.floor(ageS / 86400)} d ago`
}

export function geoErrorMessage(status: number, body: unknown): string {
  const b = (body && typeof body === 'object' ? body : {}) as { code?: string; message?: string }
  switch (b.code) {
    case 'invalid_box': return 'That map area is not valid. Press "Fit to data" and try again.'
    case 'invalid_coordinates': return 'A coordinate is outside the valid range.'
    case 'invalid_point': return 'A point must have a latitude and a longitude.'
  }
  if (status === 401) return 'The token was not accepted (missing, wrong or expired).'
  if (status === 403) return 'Your role may not read this data (the spec lists read roles per block).'
  return b.message || `The API answered ${status}.`
}
