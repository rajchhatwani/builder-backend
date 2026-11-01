/** Deep-link contract: every URL shape that works today must keep resolving to the same screen.
 *  Bookmarks, invitation e-mails and the SSO callback depend on these. Do not edit a row to make
 *  a refactor pass: a changed row is a broken link. */
import { describe, expect, it } from 'vitest'
import { parseHash } from './App'

const PID = '3f2a1c9e-0000-4000-8000-000000000001'

const CONTRACT: [string, unknown][] = [
  ['', { page: 'projects' }],
  ['#/', { page: 'projects' }],
  ['#/something-unknown', { page: 'projects' }],
  ['#/account', { page: 'account' }],
  ['#/invitations', { page: 'invitations' }],
  ['#/invite/tok123', { page: 'invitations', token: 'tok123' }],
  ['#/invite/a%20b?x=1', { page: 'invitations', token: 'a b' }],
  ['#/sso/complete', { page: 'sso-complete' }],
  ['#/org/acme', { page: 'org', slug: 'acme', tab: 'people' }],
  ['#/org/acme/people', { page: 'org', slug: 'acme', tab: 'people' }],
  ['#/org/acme/invites', { page: 'org', slug: 'acme', tab: 'invites' }],
  ['#/org/acme/projects', { page: 'org', slug: 'acme', tab: 'projects' }],
  ['#/org/acme/plan', { page: 'org', slug: 'acme', tab: 'plan' }],
  ['#/org/acme/audit', { page: 'org', slug: 'acme', tab: 'audit' }],
  ['#/org/acme/sso', { page: 'org', slug: 'acme', tab: 'sso' }],
  ['#/org/acme/policies', { page: 'org', slug: 'acme', tab: 'policies' }],
  ['#/org/acme/nonsense', { page: 'org', slug: 'acme', tab: 'people' }],
  ['#/admin', { page: 'admin', section: 'overview' }],
  ['#/admin/', { page: 'admin', section: 'overview' }],
  ['#/admin/insights', { page: 'admin', section: 'insights' }],
  ['#/admin/users', { page: 'admin', section: 'users' }],
  ['#/admin/organizations', { page: 'admin', section: 'organizations' }],
  ['#/admin/billing', { page: 'admin', section: 'billing' }],
  ['#/admin/plans', { page: 'admin', section: 'plans' }],
  ['#/admin/projects', { page: 'admin', section: 'projects' }],
  ['#/admin/audit', { page: 'admin', section: 'audit' }],
  ['#/admin/settings', { page: 'admin', section: 'settings' }],
  ['#/admin/nonsense', { page: 'admin', section: 'overview' }],
  [`#/p/${PID}`, { page: 'project', projectId: PID, section: 'overview' }],
  // Added by F1-4 (an addition, no existing row changed): the v2-only State machines page.
  [`#/p/${PID}/machines`, { page: 'project', projectId: PID, section: 'machines' }],
  // Added by F1-6A (additions, no existing row changed): the v2-only Settings and Change history pages.
  [`#/p/${PID}/settings`, { page: 'project', projectId: PID, section: 'settings' }],
  [`#/p/${PID}/history`, { page: 'project', projectId: PID, section: 'history' }],
  // Added by F1-5 (addition, no existing row changed): the v2-only Hooks page.
  [`#/p/${PID}/hooks`, { page: 'project', projectId: PID, section: 'hooks' }],
  // Added by F1-6B (addition, no existing row changed): the v2-only Seed data page.
  [`#/p/${PID}/seed`, { page: 'project', projectId: PID, section: 'seed' }],
  // Added by F1-3 (addition, no existing row changed): the v2-only Rules (expression checker) page.
  [`#/p/${PID}/rules`, { page: 'project', projectId: PID, section: 'rules' }],
  [`#/p/${PID}/nonsense`, { page: 'project', projectId: PID, section: 'overview' }],
]

describe('hash routes', () => {
  it.each(CONTRACT)('%s resolves as before', (hash, expected) => {
    expect(parseHash(hash)).toEqual(expected)
  })

  it('every project section resolves to itself', async () => {
    const { SECTIONS } = await import('./components/Sidebar')
    expect(SECTIONS.length).toBeGreaterThan(10)
    for (const s of SECTIONS) {
      expect(parseHash(`#/p/${PID}/${s.id}`)).toEqual({ page: 'project', projectId: PID, section: s.id })
    }
  })
})
