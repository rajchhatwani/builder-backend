import { describe, expect, it } from 'vitest'
import {
  ageSeconds, boxQuery, clusterByGrid, dataPoints, fitBounds, formatAge, formatMicro, formatPoint, freshness, geofencesContaining,
  geoErrorMessage, makeProjection, pointInGeofence, zoomBounds, MIN_SPAN, VIEW_H, VIEW_W, WORLD, type Geofence,
} from './mapLogic'

const P = (lat: number, lng: number) => ({ lat_micro: lat, lng_micro: lng })

describe('formatMicro', () => {
  it('formats with integer maths', () => {
    expect(formatMicro(12_345_678)).toBe('12.345678')
    expect(formatMicro(-500)).toBe('-0.000500')
    expect(formatMicro(0)).toBe('0.000000')
    expect(formatMicro(-180_000_000)).toBe('-180.000000')
    expect(formatMicro(1.5)).toBe('0.000000')
    expect(formatPoint(P(1_000_000, -2_500_000))).toBe('1.000000, -2.500000')
  })
})

describe('fitBounds', () => {
  it('returns null for an empty set', () => expect(fitBounds([])).toBeNull())
  it('boxes a single point with the minimum span', () => {
    const b = fitBounds([P(10_000_000, 20_000_000)])!
    expect(b).toEqual({ minLat: 10_000_000 - MIN_SPAN, maxLat: 10_000_000 + MIN_SPAN, minLng: 20_000_000 - MIN_SPAN, maxLng: 20_000_000 + MIN_SPAN })
  })
  it('pads many points by an eighth and never leaves the globe', () => {
    const b = fitBounds([P(0, 0), P(8_000_000, 16_000_000)])!
    expect(b).toEqual({ minLat: -1_000_000, maxLat: 9_000_000, minLng: -2_000_000, maxLng: 18_000_000 })
    const edge = fitBounds([P(90_000_000, 180_000_000), P(-90_000_000, -180_000_000)])!
    expect(edge).toEqual(WORLD)
  })
  it('keeps minLng <= maxLng for any input (no antimeridian wrap)', () => {
    const b = fitBounds([P(0, 179_999_000), P(0, -179_999_000)])!
    expect(b.minLng).toBeLessThanOrEqual(b.maxLng)
  })
})

describe('zoomBounds / boxQuery', () => {
  it('halves the span around the centre and keeps a minimum', () => {
    const z = zoomBounds({ minLat: 0, maxLat: 4_000_000, minLng: 0, maxLng: 8_000_000 }, 1, 2)
    expect(z).toEqual({ minLat: 1_000_000, maxLat: 3_000_000, minLng: 2_000_000, maxLng: 6_000_000 })
    const tiny = zoomBounds({ minLat: 0, maxLat: 100, minLng: 0, maxLng: 100 }, 1, 2)
    expect(tiny.maxLat - tiny.minLat).toBe(2 * MIN_SPAN)
    expect(zoomBounds(WORLD, 2, 1)).toEqual(WORLD)
  })
  it('writes the four contract parameters', () => {
    expect(boxQuery({ minLat: 1, minLng: 2, maxLat: 3, maxLng: 4 })).toBe('min_lat_micro=1&min_lng_micro=2&max_lat_micro=3&max_lng_micro=4')
  })
})

describe('makeProjection', () => {
  const b = { minLat: 0, maxLat: 10_000_000, minLng: 0, maxLng: 10_000_000 }
  const pr = makeProjection(b)
  it('puts north up and fits inside the view', () => {
    const nw = pr.project(P(10_000_000, 0)), se = pr.project(P(0, 10_000_000))
    expect(nw.y).toBeLessThan(se.y)
    expect(nw.x).toBeLessThan(se.x)
    for (const p of [nw, se]) { expect(p.x).toBeGreaterThanOrEqual(-0.001); expect(p.x).toBeLessThanOrEqual(VIEW_W + 0.001); expect(p.y).toBeGreaterThanOrEqual(-0.001); expect(p.y).toBeLessThanOrEqual(VIEW_H + 0.001) }
  })
  it('keeps the box centre at the view centre and tests membership', () => {
    const c = pr.project(P(5_000_000, 5_000_000))
    expect(c.x).toBeCloseTo(VIEW_W / 2, 3)
    expect(c.y).toBeCloseTo(VIEW_H / 2, 3)
    expect(pr.inView(P(5_000_000, 5_000_000))).toBe(true)
    expect(pr.inView(P(-1, 5_000_000))).toBe(false)
  })
  it('scales metres to pixels linearly', () => {
    expect(pr.metresToPx(2000)).toBeCloseTo(2 * pr.metresToPx(1000), 6)
  })
  it('survives a degenerate (zero-span) box', () => {
    const d = makeProjection({ minLat: 5, maxLat: 5, minLng: 5, maxLng: 5 })
    const p = d.project(P(5, 5))
    expect(Number.isFinite(p.x) && Number.isFinite(p.y)).toBe(true)
  })
})

const circle: Geofence = { id: 'c', name: 'Depot', shape: 'circle', center: P(0, 0), radius_m: 1000, vertices: null }
const square: Geofence = { id: 's', name: 'Zone', shape: 'polygon', center: null, radius_m: null, vertices: [P(0, 0), P(0, 10_000_000), P(10_000_000, 10_000_000), P(10_000_000, 0)] }
const concave: Geofence = { id: 'v', name: 'L', shape: 'polygon', center: null, radius_m: null, vertices: [P(0, 0), P(0, 4_000_000), P(2_000_000, 4_000_000), P(2_000_000, 2_000_000), P(4_000_000, 2_000_000), P(4_000_000, 0)] }

describe('pointInGeofence', () => {
  it('circle: inside, on the border and outside (1000 m is about 8983 micro-degrees)', () => {
    expect(pointInGeofence(P(0, 0), circle)).toBe(true)
    expect(pointInGeofence(P(8_000, 0), circle)).toBe(true)
    expect(pointInGeofence(P(9_000, 0), circle)).toBe(false)
    expect(pointInGeofence(P(0, 20_000), circle)).toBe(false)
  })
  it('circle: invalid shapes are never inside', () => {
    expect(pointInGeofence(P(0, 0), { ...circle, radius_m: 0 })).toBe(false)
    expect(pointInGeofence(P(0, 0), { ...circle, center: null })).toBe(false)
  })
  it('polygon: inside, outside, border and vertex', () => {
    expect(pointInGeofence(P(5_000_000, 5_000_000), square)).toBe(true)
    expect(pointInGeofence(P(-1, 5_000_000), square)).toBe(false)
    expect(pointInGeofence(P(0, 5_000_000), square)).toBe(true)
    expect(pointInGeofence(P(10_000_000, 10_000_000), square)).toBe(true)
  })
  it('polygon: concave notch is outside, large micro values do not overflow', () => {
    expect(pointInGeofence(P(3_000_000, 3_000_000), concave)).toBe(false)
    expect(pointInGeofence(P(1_000_000, 3_000_000), concave)).toBe(true)
    const big: Geofence = { ...square, vertices: [P(-90_000_000, -180_000_000), P(-90_000_000, 180_000_000), P(90_000_000, 180_000_000), P(90_000_000, -180_000_000)] }
    expect(pointInGeofence(P(89_999_999, 179_999_999), big)).toBe(true)
  })
  it('polygon with fewer than 3 vertices is never inside; containing() filters', () => {
    expect(pointInGeofence(P(0, 0), { ...square, vertices: [P(0, 0), P(1, 1)] })).toBe(false)
    expect(geofencesContaining(P(1_000, 1_000), [circle, square]).map((g) => g.id)).toEqual(['c', 's'])
    expect(geofencesContaining(P(50_000_000, 50_000_000), [circle, square])).toEqual([])
  })
})

describe('dataPoints', () => {
  it('adds polygon vertices and circle extents', () => {
    expect(dataPoints([P(1, 1)], [P(2, 2)], [square, circle])).toHaveLength(1 + 1 + 4 + 2)
    expect(dataPoints([], [], [])).toEqual([])
  })
})

describe('clusterByGrid', () => {
  const pr = makeProjection({ minLat: 0, maxLat: 10_000_000, minLng: 0, maxLng: 10_000_000 })
  it('returns no clusters for an empty set', () => expect(clusterByGrid([], pr)).toEqual([]))
  it('keeps a single point as a cluster of one', () => {
    const c = clusterByGrid([P(1, 1)], pr)
    expect(c).toHaveLength(1)
    expect(c[0].items).toHaveLength(1)
  })
  it('merges close points and keeps distant ones apart', () => {
    const items = [P(5_000_000, 5_000_000), P(5_000_100, 5_000_100), P(9_000_000, 1_000_000)]
    const c = clusterByGrid(items, pr, 40)
    expect(c.map((x) => x.items.length).sort()).toEqual([1, 2])
    const merged = c.find((x) => x.items.length === 2)!
    expect(merged.x).toBeCloseTo(pr.project(items[0]).x, 0)
  })
  it('never loses or duplicates an item and a tiny cell separates everything', () => {
    const items = Array.from({ length: 25 }, (_, i) => P(i * 400_000, i * 400_000))
    expect(clusterByGrid(items, pr, 5000).reduce((n, c) => n + c.items.length, 0)).toBe(25)
    expect(clusterByGrid(items, pr, 0.0001)).toHaveLength(25)
    expect(clusterByGrid(items, pr, 1e9)).toHaveLength(1)
  })
})

describe('age and freshness', () => {
  const now = Date.parse('2026-01-01T00:10:00Z')
  it('computes age and never goes negative', () => {
    expect(ageSeconds('2026-01-01T00:09:30Z', now)).toBe(30)
    expect(ageSeconds('2026-01-01T00:20:00Z', now)).toBe(0)
    expect(ageSeconds('garbage', now)).toBe(Infinity)
  })
  it('classifies at the 60 s and 300 s edges', () => {
    expect(freshness(59)).toBe('fresh'); expect(freshness(60)).toBe('aging'); expect(freshness(299)).toBe('aging'); expect(freshness(300)).toBe('stale'); expect(freshness(Infinity)).toBe('stale')
  })
  it('formats ages', () => {
    expect([5, 120, 7200, 172800, Infinity].map(formatAge)).toEqual(['5s ago', '2 min ago', '2 h ago', '2 d ago', 'unknown age'])
  })
})

describe('geoErrorMessage', () => {
  it('maps codes and statuses', () => {
    expect(geoErrorMessage(422, { code: 'invalid_box' })).toMatch(/not valid/)
    expect(geoErrorMessage(401, {})).toMatch(/token was not accepted/)
    expect(geoErrorMessage(403, null)).toMatch(/may not read/)
    expect(geoErrorMessage(500, { message: 'boom' })).toBe('boom')
    expect(geoErrorMessage(500, null)).toBe('The API answered 500.')
  })
})
