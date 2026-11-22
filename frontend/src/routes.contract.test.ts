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
  // Added by CP-5V (additions): the org AI and Usage tabs.
  ['#/org/acme/ai', { page: 'org', slug: 'acme', tab: 'ai' }],
  ['#/org/acme/usage', { page: 'org', slug: 'acme', tab: 'usage' }],
  ['#/verify-email', { page: 'verify-email' }],
  ['#/__spike', { page: 'spike' }],
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
  // Added by CP-5V (addition): the platform-admin SSO domain release page.
  ['#/admin/sso', { page: 'admin', section: 'sso' }],
  ['#/admin/previews', { page: 'admin', section: 'previews' }],
  ['#/admin/operations', { page: 'admin', section: 'operations' }],
  ['#/admin/usage', { page: 'admin', section: 'usage' }],
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
  // Added by F4-4 (addition): the v2-only Access matrix page (the id 'access' already means the classic Authorization panel).
  [`#/p/${PID}/permissions`, { page: 'project', projectId: PID, section: 'permissions' }],
  // Added by F4-6 (addition): the v2-only Visual spec diff page.
  [`#/p/${PID}/specdiff`, { page: 'project', projectId: PID, section: 'specdiff' }],
  // Added by F4-7 (addition): the v2-only Suite identity page.
  [`#/p/${PID}/suite`, { page: 'project', projectId: PID, section: 'suite' }],
  // Added by F4-1 (addition): the v2-only Import wizard page.
  [`#/p/${PID}/import`, { page: 'project', projectId: PID, section: 'import' }],
  // Added by CP-5V (additions): the v2-only Search and Dependencies pages.
  [`#/p/${PID}/search`, { page: 'project', projectId: PID, section: 'search' }],
  [`#/p/${PID}/dependencies`, { page: 'project', projectId: PID, section: 'dependencies' }],
  // Added by F5-1 (addition): the v2-only Ledger explorer page.
  [`#/p/${PID}/ledger`, { page: 'project', projectId: PID, section: 'ledger' }],
  [`#/p/${PID}/map`, { page: 'project', projectId: PID, section: 'map' }],
  [`#/p/${PID}/bookings`, { page: 'project', projectId: PID, section: 'bookings' }],
  [`#/p/${PID}/documents`, { page: 'project', projectId: PID, section: 'documents' }],
  [`#/p/${PID}/agentactions`, { page: 'project', projectId: PID, section: 'agentactions' }],
  [`#/p/${PID}/apikeys`, { page: 'project', projectId: PID, section: 'apikeys' }],
  [`#/p/${PID}/apps`, { page: 'project', projectId: PID, section: 'apps' }],
  [`#/p/${PID}/compliance`, { page: 'project', projectId: PID, section: 'compliance' }],
  // Added by F2-1 (addition, no existing row changed): the v2-only Forms preview page.
  // Added by F2-4 (addition): the v2-only History timeline page.
  [`#/p/${PID}/timeline`, { page: 'project', projectId: PID, section: 'timeline' }],
  [`#/p/${PID}/forms`, { page: 'project', projectId: PID, section: 'forms' }],
  // Added by F2-6 (addition): the v2-only Notifications page.
  [`#/p/${PID}/notifications`, { page: 'project', projectId: PID, section: 'notifications' }],
  // Added by F2-2/F2-3 (additions): the v2-only Connect and Operate pages.
  [`#/p/${PID}/webhooks`, { page: 'project', projectId: PID, section: 'webhooks' }],
  [`#/p/${PID}/providers`, { page: 'project', projectId: PID, section: 'providers' }],
  [`#/p/${PID}/jobs`, { page: 'project', projectId: PID, section: 'jobs' }],
  [`#/p/${PID}/workers`, { page: 'project', projectId: PID, section: 'workers' }],
  [`#/p/${PID}/workflows`, { page: 'project', projectId: PID, section: 'workflows' }],
  // Added by F4-5 (addition): the v2-only Traces page.
  [`#/p/${PID}/traces`, { page: 'project', projectId: PID, section: 'traces' }],
  // Added by F4-3 (addition): the v2-only Metrics & reports page.
  [`#/p/${PID}/metrics`, { page: 'project', projectId: PID, section: 'metrics' }],
  [`#/p/${PID}/nonsense`, { page: 'project', projectId: PID, section: 'overview' }],
]

describe('hash routes', () => {
  it.each(CONTRACT)('%s resolves as before', (hash, expected) => {
    expect(parseHash(hash)).toEqual(expected)
  })

  it('every project section resolves to itself', async () => {
    const { SECTIONS } = await import('./components/Sidebar')
    const { V2_SECTIONS } = await import('./shell/pages')
    expect(SECTIONS.length).toBeGreaterThan(10)
    expect(V2_SECTIONS.length).toBeGreaterThan(10)
    for (const s of [...SECTIONS, ...V2_SECTIONS]) {
      expect(parseHash(`#/p/${PID}/${s.id}`)).toEqual({ page: 'project', projectId: PID, section: s.id })
    }
  })
})
