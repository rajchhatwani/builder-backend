import { describe, expect, it, vi } from 'vitest'
import { parseEnvelope, keysForEvent, projectKeys, topicsForEvent } from './eventRouting'
import { applyEvent } from './useProjectEvents'
import { subscribeTopic } from './bus'

const P = 'p1'
describe('event routing', () => {
  it('spec.changed refreshes spec, status, ops, timeline, history', () => {
    expect(keysForEvent({ topic: 'spec', type: 'spec.changed' }, P)).toEqual([
      ['spec', P], ['project-status', P], ['ops', P], ['timeline', P], ['history', P],
    ])
  })
  it('import.committed refreshes imports and records', () => {
    const keys = keysForEvent({ topic: 'imports', type: 'import.committed' }, P)
    expect(keys).toContainEqual(['imports', P])
    expect(keys).toContainEqual(['records', P])
  })
  it('resync invalidates everything, unknown events nothing', () => {
    expect(keysForEvent({ topic: 'system', type: 'resync' }, P)).toHaveLength(Object.keys(projectKeys).length)
    expect(keysForEvent({ topic: 'x', type: 'future.thing' }, P)).toEqual([])
    expect(topicsForEvent({ topic: 'x', type: 'future.thing' })).toEqual([])
  })
  it('applyEvent calls invalidateQueries per key and publishes the page topic', () => {
    const qc = { invalidateQueries: vi.fn().mockResolvedValue(undefined) }
    const seen = vi.fn()
    const off = subscribeTopic('spec', seen)
    applyEvent(qc, P, { id: 3, topic: 'spec', type: 'spec.changed', data: {} })
    off()
    expect(qc.invalidateQueries).toHaveBeenCalledTimes(5)
    expect(qc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['timeline', P] })
    expect(seen).toHaveBeenCalledTimes(1)
  })
  it('applyEvent on resync invalidates all keys', () => {
    const qc = { invalidateQueries: vi.fn().mockResolvedValue(undefined) }
    applyEvent(qc, P, { id: 9, topic: 'system', type: 'resync', data: {} })
    expect(qc.invalidateQueries).toHaveBeenCalledTimes(Object.keys(projectKeys).length)
  })
  it('parseEnvelope reads the server envelope and rejects junk', () => {
    const body = JSON.stringify({ id: 7, project_id: P, topic: 'spec', type: 'spec.changed', data: { seq: 2 }, at: 'x' })
    expect(parseEnvelope({ id: '7', event: 'spec.changed', data: body })).toEqual({ id: 7, topic: 'spec', type: 'spec.changed', data: { seq: 2 } })
    expect(parseEnvelope({ event: 'x', data: 'nope' })).toBeNull()
    expect(parseEnvelope({ event: 'x', data: '[1]' })).toBeNull()
    expect(parseEnvelope({ id: 'abc', event: 'x', data: '{}' })?.id).toBeNull()
  })
})
