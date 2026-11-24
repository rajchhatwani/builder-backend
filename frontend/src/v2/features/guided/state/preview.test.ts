import { describe, expect, it } from 'vitest'
import { checkReducer, consoleReducer, credentialsReducer, initialChecks, logReducer } from './preview'

describe('preview state', () => {
  it('rejects a late sign-in when the preview token has been replaced', () => {
    const first = credentialsReducer({}, { type: 'connect', id: 'id', token: 'first' })
    const latest = credentialsReducer(first, { type: 'connect', id: 'id', token: 'second' })
    expect(credentialsReducer(latest, { type: 'identity', id: 'id', token: 'first', bearer: 'stale' })).toBe(latest)
    expect(credentialsReducer(latest, { type: 'stop', id: 'id' })).toEqual({})
  })

  it('resets dependent results when a new create changes the record', () => {
    const pass = { verdict: 'pass' as const }
    const before = checkReducer(initialChecks, { type: 'result', check: 'list', result: pass })
    const later = checkReducer({ ...before, results: { ...before.results, read: pass, update: pass } },
      { type: 'result', check: 'create', record: 'new', result: pass })
    expect(later).toEqual({ record: 'new', results: { list: pass, create: pass } })
  })

  it('keeps receiving logs while display is paused', () => {
    const start = { lines: ['first'], status: 'live' }
    const paused = logReducer(start, { type: 'pause' })
    const update = logReducer(paused, { type: 'line', text: 'next' })
    expect(update.frozen).toEqual(['first'])
    expect(logReducer(update, { type: 'pause' })).toEqual({ lines: ['first', 'next'], status: 'live' })
  })

  it('bounds in-memory request history', () => {
    const previous = Array.from({ length: 20 }, () => ({ request: 'older', response: 'ok' }))
    const newest = { request: 'new', response: 'ok' }
    expect(consoleReducer(previous, newest)).toEqual([newest, ...previous.slice(0, 19)])
  })
})
