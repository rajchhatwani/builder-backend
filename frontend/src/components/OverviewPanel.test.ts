import { describe, expect, it } from 'vitest'
import { requiredEnvVars } from './NextSteps'
import { sectionForIssue } from './OverviewPanel'

const issue = (path: string, code = 'x') => ({ path, code, message: '', severity: 'error' }) as never

describe('sectionForIssue', () => {
  it('routes by path', () => {
    expect(sectionForIssue(issue('payments.payable'))).toBe('payments')
    expect(sectionForIssue(issue('auth.keycloak.realm'))).toBe('keycloak')
    expect(sectionForIssue(issue('auth.roles'))).toBe('access')
    expect(sectionForIssue(issue('auth.x'))).toBe('auth')
    expect(sectionForIssue(issue('entities.a'))).toBe('model')
    expect(sectionForIssue(issue('a', 'authz.bad'))).toBe('access')
  })
})

describe('requiredEnvVars', () => {
  it('is empty when auth is off, and HS256 needs a JWT secret', () => {
    expect(requiredEnvVars(null)).toEqual([])
    expect(requiredEnvVars({ enabled: false } as never)).toEqual([])
    const names = requiredEnvVars({ enabled: true, provider: 'builtin', jwt_algorithm: 'HS256', smtp_config: null } as never).map((v) => v.name)
    expect(names).toContain('AUTH_JWT_SECRET')
  })
  it('adds SMTP credentials when SMTP is configured', () => {
    const names = requiredEnvVars({ enabled: true, provider: 'builtin', jwt_algorithm: 'RS256', smtp_config: { host: 'h', port: 25 } } as never).map((v) => v.name)
    expect(names).toEqual(expect.arrayContaining(['AUTH_JWT_PRIVATE_KEY', 'SMTP_USERNAME', 'SMTP_PASSWORD']))
  })
})
