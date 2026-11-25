import { expect, it } from 'vitest'
import { accountMfaReducer, idleMfa } from './accountMfa'

const setup = { secret: 'test-key', otpauth_uri: 'otpauth://totp/test' }
const codes = ['TEST-ONLY']

it('replaces the setup secret with recovery codes and clears those after acknowledgement', () => {
  const started = accountMfaReducer(idleMfa, { type: 'start', step: 'setup' })
  const scan = accountMfaReducer(started, { type: 'scan', setup })
  expect(scan).toEqual({ step: 'scan', setup })
  const recovery = accountMfaReducer(scan, { type: 'recovery', codes })
  expect(recovery).toEqual({ step: 'codes', codes })
  expect(accountMfaReducer(recovery, { type: 'start', step: 'disable' })).toBe(recovery)
  expect(accountMfaReducer(recovery, { type: 'complete' })).toBe(idleMfa)
})

it('rejects an out-of-order enrollment response and accepts replacement recovery codes', () => {
  expect(accountMfaReducer(idleMfa, { type: 'scan', setup })).toBe(idleMfa)
  expect(accountMfaReducer(idleMfa, { type: 'recovery', codes })).toBe(idleMfa)
  const started = accountMfaReducer(idleMfa, { type: 'start', step: 'regenerate' })
  expect(accountMfaReducer(started, { type: 'recovery', codes })).toEqual({ step: 'codes', codes })
})
