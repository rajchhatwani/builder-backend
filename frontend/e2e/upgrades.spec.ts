/** CP-6E/6I: Ship > Upgrades. Scorecard with a fix action, create a proposal, read it, download its patch, dismiss it.
 *  The project is real; the upgrade and scorecard answers are mocked at the builder API (a fresh project has no previous generation, so a
 *  real proposal cannot be made without a generate/download first). One real call checks the scorecard contract.
 *  Not run by its author; run with `npx playwright test e2e/upgrades.spec.ts`. */
import { expect, test } from '@playwright/test'
import { API, createProjectViaApi, expectAxeClean, signedInUser, watchProblems } from './helpers'
import { mockBuilder } from './preview-mock'

const UID = 'aaaaaaaa-1111-4222-8333-444444444444'
const PATCH = 'diff --git a/app/main.py b/app/main.py\n--- a/app/main.py\n+++ b/app/main.py\n@@ -1 +1 @@\n-old\n+new\n'

test('upgrades: scorecard, create a proposal, read it, download the patch, dismiss it', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Upgrades Project')

  const real = await (await api.get(`/projects/${id}/scorecard`)).json()
  expect(typeof real.score).toBe('number')
  expect(Array.isArray(real.checks)).toBe(true)

  const summary = {
    id: UID, project_id: id, base_generation_id: 'gen1', status: 'open', from_generator_version: '1.4.0', to_generator_version: '1.5.0',
    block_changes: [{ block: 'auth', from: '1.0.0', to: '1.0.1', bump: 'patch' }], file_count: 2, auto_apply_eligible: true,
    created_at: '2026-11-20T10:00:00Z', decided_at: null as string | null,
  }
  const detail = () => ({
    ...summary, created_by: null, patch_size: PATCH.length, kept: ['app/custom/hooks.py'],
    files: [{ path: 'app/main.py', zone: 'generated', change: 'modified' }, { path: 'requirements.txt', zone: 'generated', change: 'modified' }],
    sbom_diff: { added: [], removed: [], changed: [{ name: 'fastapi', from: '0.115.0', to: '0.115.2' }] }, migrations: [], scorecard: { passing: true },
  })
  let created = false
  const seen = await mockBuilder(page, new RegExp(`^${API}/projects/${id}/(scorecard|upgrades)`), (r) => {
    if (r.method === 'GET' && r.path.endsWith('/scorecard')) {
      return { json: { score: 82, passing: true, checks: [
        { id: 'jwt_secret_strength', group: 'security', status: 'pass', detail: 'ok', fix: { action: 'none', route: '' } },
        { id: 'fastapi_age', group: 'dependency_freshness', status: 'warn', detail: 'fastapi is 2 minor versions behind', fix: { action: 'open_upgrade', route: `/p/${id}/upgrades` } },
        { id: 'hooks_declared', group: 'hook_coverage', status: 'fail', detail: 'a hook is not declared', fix: { action: 'redeclare_hook', route: `/p/${id}/hooks` } },
      ] } }
    }
    if (r.method === 'GET' && r.path.endsWith('/upgrades')) return { json: { items: created ? [{ ...summary }] : [], total: created ? 1 : 0, limit: 50, offset: 0 } }
    if (r.method === 'POST' && r.path.endsWith('/upgrades')) { created = true; return { status: 201, json: detail() } }
    if (r.method === 'GET' && r.path.endsWith(`/upgrades/${UID}`)) return { json: detail() }
    if (r.method === 'GET' && r.path.endsWith('/patch')) return { text: PATCH, contentType: 'text/x-diff' }
    if (r.method === 'POST' && r.path.endsWith('/dismiss')) { summary.status = 'dismissed'; summary.decided_at = '2026-11-22T09:00:00Z'; return { json: detail() } }
    return undefined
  })
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/upgrades`)
  await expect(page.getByRole('heading', { level: 1, name: 'Upgrades' })).toBeVisible()
  await expect(page.getByTestId('score')).toHaveText('Score 82 / 100')
  await expect(page.getByTestId('passing')).toContainText('Passing')
  await expect(page.getByTestId('check-group')).toHaveCount(3)
  await expect(page.getByTestId('check')).toHaveCount(3)
  await expect(page.locator('[data-testid=check][data-status=fail]')).toContainText('a hook is not declared')
  await expect(page.getByTestId('fix-hook')).toHaveAttribute('href', `#/p/${id}/hooks`)
  await expect(page.getByTestId('list-empty')).toBeVisible()

  // Create a proposal from the scorecard's own fix button.
  await page.getByTestId('fix-open-upgrade').click()
  await expect(page.getByTestId('proposal')).toHaveCount(1)
  await expect(page.getByTestId('proposal-status')).toHaveText('open')
  await expect(page.getByTestId('detail-status')).toContainText('1.4.0 to 1.5.0')
  await expect(page.getByTestId('block-changes')).toContainText('auth')
  await expect(page.getByTestId('file-row')).toHaveCount(2)
  await expect(page.getByTestId('kept')).toContainText('app/custom/hooks.py')
  await expect(page.getByTestId('sbom')).toContainText('fastapi')
  await expect(page.getByTestId('eligibility')).toContainText('Eligible')
  await expect(page.getByTestId('patch')).toContainText('+new')
  await expect(page.getByTestId('apply-command')).toHaveText('git apply --3way upgrade-aaaaaaaa.patch')

  const [download] = await Promise.all([page.waitForEvent('download'), page.getByTestId('download-patch').click()])
  expect(download.suggestedFilename()).toBe('upgrade-aaaaaaaa.patch')

  // Dismiss asks first.
  await page.getByTestId('dismiss').click()
  await expect(page.getByText('Dismiss this proposal?')).toBeVisible()
  expect(seen.some((s) => s.path.endsWith('/dismiss'))).toBe(false)
  await page.getByTestId('confirm-decide').click()
  await expect(page.getByTestId('closed-note')).toContainText('This proposal is dismissed')
  await expect(page.getByTestId('proposal-status')).toHaveText('dismissed')
  expect(seen.filter((s) => s.method === 'POST').map((s) => s.path.split('/').pop())).toEqual(['upgrades', 'dismiss'])

  await expectAxeClean(page, 'upgrades page')
  watch.assertNone()
})
