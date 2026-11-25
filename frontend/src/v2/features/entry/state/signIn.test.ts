import { expect, it } from 'vitest'
import { initialSignIn, signInReducer } from './signIn'

it('keeps the discovered email through SSO fallback and MFA, then clears recovery state on reset', () => {
  const email = 'reader@example.test'
  const sso = signInReducer(initialSignIn, { type: 'discovered', email,
    result: { method: 'sso', login_url: 'https://api.example.test/sso/library/login', organization_name: 'Library' } })
  expect(sso).toMatchObject({ step: 'sso', email, organization: 'Library' })
  const password = signInReducer(sso, { type: 'password' })
  expect(password).toEqual({ step: 'password', email })
  const mfa = signInReducer(password, { type: 'challenge', challenge: {
    mfa_required: true, enrollment_required: false, mfa_token: 'pending', expires_in: 300, methods: ['totp', 'recovery_code'],
  } })
  expect(mfa).toMatchObject({ step: 'mfa', email })
  expect(signInReducer(mfa, { type: 'reset' })).toEqual(initialSignIn)
})

it('offers password sign-in when an SSO response has an unusable URL', () => {
  expect(signInReducer(initialSignIn, { type: 'discovered', email: 'reader@example.test',
    result: { method: 'sso', login_url: 'javascript:void(0)' } })).toMatchObject({ step: 'password' })
})
