import { describe, expect, it } from 'vitest'
import { toWrite } from './KeycloakPanel'

describe('KeycloakPanel toWrite', () => {
  it('sends cleared optional identity-provider fields as null, trimmed', () => {
    const form = {
      mode: 'own', realm: 'r', apiClientId: 'a', webClientId: 'w', redirectUris: '',
      passwordMinLength: 8, mfa: 'off', sessionIdleMinutes: 30, sessionMaxHours: 8, auditRetentionDays: 30,
      sourceProjectId: '',
      providers: [{
        alias: 'g', type: 'google', display_name: 'Google', client_id: ' id ', tenant_id: '',
        hosted_domain: '', issuer: ' ', authorization_url: '', token_url: '', jwks_url: '', userinfo_url: '',
      }],
    }
    const idp = toWrite(form as never).identity_providers[0]
    expect(idp.hosted_domain).toBeNull()
    expect(idp.userinfo_url).toBeNull()
    expect(idp.issuer).toBeNull()
    expect(idp.tenant_id).toBeNull()
    expect(idp.client_id).toBe('id')
    expect(idp.display_name).toBe('Google')
  })
})
