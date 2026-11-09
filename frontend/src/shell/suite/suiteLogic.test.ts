import { describe, expect, it } from 'vitest'
import type { KeycloakConfig, SuiteRef } from '../../api/types'
import { EMPTY_FORM, formFromSuite, hints, isDirty, keycloakBodyForSuite, patchBody, suiteFromForm, suiteIssues, suiteRealm } from './suiteLogic'

describe('suite form round trip', () => {
  it('returns the API body unchanged when nothing is edited', () => {
    for (const suite of [
      { suite_id: 'acme', hub_issuer: 'https://id.acme.com/realms/suite-acme', join_state: 'joined' },
      { suite_id: 'a1-b2', hub_issuer: null, join_state: 'none' },
      { suite_id: 'x', hub_issuer: null, join_state: 'planned' },
    ] as SuiteRef[]) {
      expect(patchBody(formFromSuite(suite))).toEqual({ suite })
      expect(isDirty(formFromSuite(suite), suite)).toBe(false)
    }
  })
  it('turns a blank hub issuer into null and trims', () => {
    expect(suiteFromForm({ enabled: true, suiteId: ' acme ', hubIssuer: '  ', joinState: 'none' })).toEqual({ suite_id: 'acme', hub_issuer: null, join_state: 'none' })
  })
  it('sends suite null to remove, and an empty saved suite is not dirty', () => {
    expect(patchBody({ ...EMPTY_FORM })).toEqual({ suite: null })
    expect(formFromSuite(null)).toEqual(EMPTY_FORM)
    expect(isDirty(EMPTY_FORM, null)).toBe(false)
    expect(isDirty(formFromSuite({ suite_id: 'a', hub_issuer: null, join_state: 'none' }), null)).toBe(true)
  })
})

describe('derived realm and Keycloak body', () => {
  it('derives suite-<id>', () => expect(suiteRealm(' acme ')).toBe('suite-acme'))
  it('keeps the other Keycloak settings and forces shared mode and the realm', () => {
    const cur = {
      id: 'k', project_id: 'p', active: true, created_at: '', updated_at: '', mode: 'own', realm: 'old', api_client_id: 'api', web_client_id: 'web',
      redirect_uris: ['https://a.example.com/cb'], password_min_length: 14, mfa: 'required', session_idle_minutes: 20, session_max_hours: 8,
      audit_retention_days: 30, identity_providers: [], source_project_id: null,
    } as KeycloakConfig
    const body = keycloakBodyForSuite(cur, 'acme')
    expect(body).toMatchObject({ mode: 'shared', realm: 'suite-acme', password_min_length: 14, mfa: 'required', redirect_uris: ['https://a.example.com/cb'], source_project_id: null })
    expect('id' in body).toBe(false)
  })
})

describe('hints', () => {
  const f = (suiteId: string, hubIssuer = '') => hints({ enabled: true, suiteId, hubIssuer, joinState: 'none' })
  it('checks the suite id', () => {
    expect(f('acme').suiteId).toBeNull()
    expect(f('').suiteId).toMatch(/Enter/)
    expect(f('Acme').suiteId).toMatch(/lowercase/)
    expect(f('acme-').suiteId).toMatch(/hyphen/)
    expect(f('a'.repeat(58)).suiteId).toMatch(/at most 57/)
  })
  it('checks the hub issuer', () => {
    expect(f('acme', 'https://id.acme.com/realms/suite-acme').hubIssuer).toBeNull()
    expect(f('acme', 'http://localhost:8080/realms/suite-acme/').hubIssuer).toBeNull()
    expect(f('acme', 'http://id.acme.com/realms/suite-acme').hubIssuer).toMatch(/https/)
    expect(f('acme', 'https://id.acme.com/realms/other').hubIssuer).toMatch(/realms\/suite-acme/)
    expect(f('acme', 'nope').hubIssuer).toMatch(/full address/)
    expect(f('acme', 'https://id.acme.com/realms/suite-acme?x=1').hubIssuer).toMatch(/query/)
  })
  it('gives no hints when the suite is off', () => expect(hints(EMPTY_FORM)).toEqual({ suiteId: null, hubIssuer: null }))
})

describe('suiteIssues', () => {
  it('keeps only suite related issues', () => {
    const issues = [
      { path: 'auth.suite', code: 'suite_requires_keycloak', message: 'a' },
      { path: 'auth.keycloak.realm', code: 'suite_realm_derived', message: 'b' },
      { path: 'entities.0', code: 'x', message: 'c' },
    ]
    expect(suiteIssues(issues).map((i) => i.message)).toEqual(['a', 'b'])
  })
})
