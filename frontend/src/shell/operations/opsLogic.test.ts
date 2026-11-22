import { describe, expect, it } from 'vitest'
import { shownText } from '../../forms/useRawText'
import {
  EMPTY_FENCE, addVertex, degText, departIso, fenceBody, fenceDraft, formatBp, formatDistance, formatDuration, formatMilli, moveVertex, opsErrorMessage,
  parseBatchRequests, parseCandidates, parseDegrees, parseFeatures, parseLat, parseLng, parseWhole, placeBody, removeVertex, setVertex, type FenceDraft,
} from './opsLogic'

describe('parseDegrees', () => {
  it.each([
    ['40', 40_000_000], ['40.', 40_000_000], ['-0.5', -500_000], ['.25', 250_000], ['0.000001', 1], ['-74.123456', -74_123_456], ['90', 90_000_000], [' 12.5 ', 12_500_000],
  ])('parses %s', (t, m) => expect(parseLat(t)).toBe(m))
  it.each(['', '-', '.', '-.', '1e3', '1,5', '1.2.3', '40.1234567', '90.000001', '+5', 'abc'])('rejects %j', (t) => expect(parseLat(t)).toBeNull())
  it('longitude allows 180 but not beyond', () => {
    expect(parseLng('-180')).toBe(-180_000_000)
    expect(parseLng('180.000001')).toBeNull()
  })
  it('stays exact for six decimals (no float drift)', () => {
    expect(parseDegrees('0.000003', 90)).toBe(3)
    expect(parseDegrees('33.333333', 90)).toBe(33_333_333)
  })
  it('degText is the inverse for micro-degrees', () => {
    for (const m of [0, 1, -1, 40_500_000, -74_000_000, 12_345_678, -500_000, 90_000_000]) expect(parseDegrees(degText(m), 180)).toBe(m)
    expect(degText(40_500_000)).toBe('40.5')
    expect(degText(-74_000_000)).toBe('-74')
    expect(degText(null)).toBe('')
  })
  it('typing character by character keeps the raw text (useRawText contract)', () => {
    for (const typed of ['-74.0', '-0.0', '40.', '-', '.', '0.50', '12.500000', '-0.000001']) {
      let value: number | null = null
      for (let i = 1; i <= typed.length; i++) {
        const text = typed.slice(0, i)
        value = parseLat(text)
        expect(shownText<number | null>(text, value, parseLat, degText)).toBe(text)
      }
    }
  })
  it('rebuilds the text when the held value changes elsewhere', () => {
    expect(shownText<number | null>('40.', 41_000_000, parseLat, degText)).toBe('41')
  })
})

describe('parseWhole', () => {
  it('accepts whole numbers in range only', () => {
    expect(parseWhole('12', 1, 50)).toBe(12)
    expect(parseWhole('0', 1, 50)).toBeNull()
    expect(parseWhole('51', 1, 50)).toBeNull()
    expect(parseWhole('1.5', 0, 9)).toBeNull()
    expect(parseWhole('', 0, 9)).toBeNull()
    expect(parseWhole('-3', -5, 5)).toBe(-3)
  })
})

describe('placeBody', () => {
  const ll = { lat: 40_500_000, lng: -74_000_000 }
  it('builds an integer micro-degree body', () => {
    expect(placeBody({ id: null, name: ' HQ ', kind: '', ll })).toEqual({ ok: true, body: { name: 'HQ', kind: null, lat_micro: 40_500_000, lng_micro: -74_000_000 } })
    expect(placeBody({ id: null, name: 'HQ', kind: 'office', ll })).toMatchObject({ ok: true, body: { kind: 'office' } })
  })
  it('refuses a missing name, a missing coordinate and long text', () => {
    expect(placeBody({ id: null, name: ' ', kind: '', ll })).toMatchObject({ ok: false })
    expect(placeBody({ id: null, name: 'x', kind: '', ll: { lat: 1, lng: null } })).toMatchObject({ ok: false })
    expect(placeBody({ id: null, name: 'x', kind: 'k'.repeat(33), ll })).toMatchObject({ ok: false })
  })
})

describe('geofence draft and vertices', () => {
  const circle: FenceDraft = { ...EMPTY_FENCE, name: 'Depot', center: { lat: 1_000_000, lng: 2_000_000 }, radius: 500 }
  it('builds a circle body without vertices', () => {
    expect(fenceBody(circle)).toEqual({ ok: true, body: { name: 'Depot', shape: 'circle', center: { lat_micro: 1_000_000, lng_micro: 2_000_000 }, radius_m: 500 } })
    expect(fenceBody({ ...circle, radius: 0 })).toMatchObject({ ok: false })
    expect(fenceBody({ ...circle, radius: null })).toMatchObject({ ok: false })
    expect(fenceBody({ ...circle, center: { lat: null, lng: 1 } })).toMatchObject({ ok: false })
  })
  it('builds a polygon body without centre or radius and names the bad vertex', () => {
    const v = [{ lat: 1, lng: 1 }, { lat: 1, lng: 2 }, { lat: 2, lng: 2 }]
    expect(fenceBody({ ...circle, shape: 'polygon', vertices: v })).toEqual({
      ok: true, body: { name: 'Depot', shape: 'polygon', vertices: v.map((p) => ({ lat_micro: p.lat, lng_micro: p.lng })) },
    })
    expect(fenceBody({ ...circle, shape: 'polygon', vertices: v.slice(0, 2) })).toMatchObject({ ok: false, error: expect.stringContaining('3') })
    expect(fenceBody({ ...circle, shape: 'polygon', vertices: [...v.slice(0, 2), { lat: 1, lng: null }] })).toMatchObject({ ok: false, error: expect.stringContaining('Vertex 3') })
  })
  it('edits vertices immutably', () => {
    const v = [{ lat: 1, lng: 1 }, { lat: 2, lng: 2 }, { lat: 3, lng: 3 }]
    expect(addVertex(v)).toHaveLength(4)
    expect(removeVertex(v, 1).map((p) => p.lat)).toEqual([1, 3])
    expect(setVertex(v, 0, { lat: 9, lng: 9 })[0].lat).toBe(9)
    expect(v[0].lat).toBe(1)
    expect(moveVertex(v, 0, 1).map((p) => p.lat)).toEqual([2, 1, 3])
    expect(moveVertex(v, 0, -1)).toBe(v)
    expect(moveVertex(v, 2, 1)).toBe(v)
  })
  it('turns a server geofence into a draft', () => {
    const d = fenceDraft({ id: 'g', name: 'N', shape: 'circle', center: { lat_micro: 5, lng_micro: 6 }, radius_m: 7, vertices: null })
    expect(d).toMatchObject({ id: 'g', shape: 'circle', center: { lat: 5, lng: 6 }, radius: 7 })
    expect(d.vertices).toHaveLength(3)
  })
})

describe('matching input', () => {
  it('parses candidates, optional fields and comments', () => {
    const r = parseCandidates('# header\nvan-1, 40.0, -74.5, 2, 4500\nvan-2')
    expect(r).toEqual({ ok: true, items: [{ id: 'van-1', lat_micro: 40_000_000, lng_micro: -74_500_000, load: 2, rating_milli: 4500 }, { id: 'van-2' }] })
  })
  it.each(['', 'a,1', 'a,95,1', 'a,1,1,-1', 'a,1,1,1,5001', 'a,1,1\na,2,2'])('rejects candidates %j', (t) => expect(parseCandidates(t)).toMatchObject({ ok: false }))
  it('parses batch requests', () => {
    expect(parseBatchRequests('R-1, 40.01, -74')).toEqual({ ok: true, items: [{ request_ref: 'R-1', point: { lat_micro: 40_010_000, lng_micro: -74_000_000 } }] })
    expect(parseBatchRequests('R-1, 40')).toMatchObject({ ok: false })
    expect(parseBatchRequests('R-1,1,1\nR-1,2,2')).toMatchObject({ ok: false })
    expect(parseBatchRequests('')).toMatchObject({ ok: false })
  })
})

describe('prediction input and formatting', () => {
  it('parses features as strict integers, booleans and text', () => {
    expect(parseFeatures('distance = 1200\nrush = true\nzone = north\nneg=-4')).toEqual({ ok: true, features: { distance: 1200, rush: true, zone: 'north', neg: -4 } })
    expect(parseFeatures('')).toEqual({ ok: true, features: {} })
  })
  it('refuses a malformed, repeated or out-of-range feature', () => {
    expect(parseFeatures('novalue')).toMatchObject({ ok: false })
    expect(parseFeatures('a=1\na=2')).toMatchObject({ ok: false })
    expect(parseFeatures('a=99999999999999999999')).toMatchObject({ ok: false })
  })
  it('formats MAE (thousandths) and coverage (basis points)', () => {
    expect(formatMilli(1500)).toBe('1.500')
    expect(formatMilli(-5)).toBe('-0.005')
    expect(formatMilli(null)).toBe('n/a')
    expect(formatBp(8525)).toBe('85.25%')
    expect(formatBp(5)).toBe('0.05%')
    expect(formatBp(null)).toBe('n/a')
  })
})

describe('routing formatting', () => {
  it('formats distance and duration', () => {
    expect(formatDistance(950)).toBe('950 m')
    expect(formatDistance(12_345)).toBe('12.34 km')
    expect(formatDuration(45)).toBe('45 s')
    expect(formatDuration(125)).toBe('2 min 5 s')
    expect(formatDuration(3720)).toBe('1 h 2 min')
  })
  it('converts a departure time', () => {
    expect(departIso('')).toBeNull()
    expect(departIso('nope')).toBeUndefined()
    expect(departIso('2026-01-01T09:30:00Z')).toBe('2026-01-01T09:30:00.000Z')
  })
})

describe('opsErrorMessage', () => {
  it('explains 403 with the block name', () => {
    expect(opsErrorMessage(403, { code: 'forbidden' }, 'geo')).toMatch(/403.*geo/)
  })
  it('explains a missing block, 401, 409, 422 detail and the generic case', () => {
    expect(opsErrorMessage(404, { detail: 'Not Found' }, 'matching')).toMatch(/no matching API/)
    expect(opsErrorMessage(404, { code: 'not_found', message: 'gone' }, 'geo')).toBe('gone')
    expect(opsErrorMessage(401, null, 'geo')).toMatch(/401/)
    expect(opsErrorMessage(409, { message: 'already decided' }, 'matching')).toBe('already decided')
    expect(opsErrorMessage(422, { detail: [{ msg: 'bad' }] }, 'geo')).toBe('bad')
    expect(opsErrorMessage(422, { code: 'invalid_coordinates', message: 'x' }, 'geo')).toMatch(/-90 to 90/)
    expect(opsErrorMessage(500, null, 'geo')).toBe('The geo API answered 500.')
  })
})
