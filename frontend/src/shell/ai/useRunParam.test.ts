import { describe, expect, it } from 'vitest'
import { ApiError } from '../../api/client'
import { errMsg } from './useRunParam'

describe('errMsg (S3-007)', () => {
  it('keeps the server code visible, with plain text for known codes', () => {
    expect(errMsg(new ApiError(403, { code: 'approval_forbidden', message: 'forbidden', details: [] }))).toContain('(approval_forbidden)')
    expect(errMsg(new ApiError(403, { code: 'approval_forbidden', message: 'forbidden', details: [] }))).toContain('Ask a project owner')
    expect(errMsg(new ApiError(409, { code: 'approval_expired', message: 'x', details: [] }))).toContain('expired')
    expect(errMsg(new ApiError(429, { code: 'weird_cap', message: 'Too many', details: [] }))).toBe('Too many (weird_cap)')
  })
  it('names a network failure and falls back for unknown values', () => {
    expect(errMsg(new TypeError('Failed to fetch'))).toContain('Could not reach the server')
    expect(errMsg('x')).toBe('Something went wrong')
    expect(errMsg(new Error('plain'))).toBe('plain')
  })
})
