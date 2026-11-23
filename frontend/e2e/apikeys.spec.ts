/** CP-6D/6I: Connect > API keys. Create a key (shown once), see it in the list, revoke it. The api_platform settings and the project
 *  come from the real builder API; the keys, catalogue and audit come from the mocked preview app (see preview-mock.ts).
 *  Not run by its author; run with `npx playwright test e2e/apikeys.spec.ts`. */
import { expect, test } from '@playwright/test'
import { createProjectViaApi, expectAxeClean, signedInUser, watchProblems } from './helpers'
import { mockPreviewSession, signInPreview } from './preview-mock'

test('api keys: create a key shown once, see it listed, revoke it', async ({ page, request }) => {
  const api = await signedInUser(page, request)
  const id = await createProjectViaApi(api, 'Api Keys Project')

  type Key = { id: string; name: string; prefix: string; kind: string; app: null; environment: string; scopes: string[]; created_at: string; expires_at: string; revoked_at: string | null; last_used_at: null; status: 'active' | 'revoked' }
  const keys: Key[] = []
  const audit: { id: string; at: string; actor: string; action: string; target: string | null; detail: Record<string, unknown> }[] = []
  const seen = await mockPreviewSession(page, id, (r) => {
    if (r.method === 'GET' && r.path === '/platform/catalogue') {
      return { json: { entities: [{ entity: 'Invoice', fields: ['number', 'total'], sandbox: true }, { entity: 'Customer', fields: ['name'], sandbox: false }], rate_limit: '600/minute', sandbox_rate_limit: '60/minute', key_ttl_days: 365 } }
    }
    if (r.method === 'GET' && r.path === '/platform/keys') return { json: keys }
    if (r.method === 'GET' && r.path === '/platform/audit') return { json: audit }
    if (r.method === 'POST' && r.path === '/platform/keys') {
      const b = r.body as { name: string; scopes: string[]; environment: string }
      const k: Key = { id: 'k1', name: b.name, prefix: 'pk_sand_ab12', kind: 'key', app: null, environment: b.environment, scopes: b.scopes, created_at: new Date().toISOString(), expires_at: new Date(Date.now() + 365 * 86_400_000).toISOString(), revoked_at: null, last_used_at: null, status: 'active' }
      keys.push(k)
      audit.push({ id: 'au1', at: k.created_at, actor: 'owner@preview.test', action: 'key.create', target: k.id, detail: { name: k.name } })
      return { status: 201, json: { id: k.id, name: k.name, prefix: k.prefix, environment: k.environment, scopes: k.scopes, expires_at: k.expires_at, key: 'pk_sand_ab12_THE-ONLY-TIME-YOU-SEE-THIS' } }
    }
    if (r.method === 'POST' && r.path === '/platform/keys/k1/revoke') {
      keys[0].status = 'revoked'; keys[0].revoked_at = new Date().toISOString()
      audit.push({ id: 'au2', at: keys[0].revoked_at, actor: 'owner@preview.test', action: 'key.revoke', target: 'k1', detail: {} })
      return { json: keys[0] }
    }
    return undefined
  })
  const watch = watchProblems(page)

  await page.goto(`/#/p/${id}/apikeys`)
  await expect(page.getByRole('heading', { level: 1, name: 'API keys' })).toBeVisible()
  expect(seen).toHaveLength(0)
  await signInPreview(page)

  await expect(page.getByTestId('catalogue-limits')).toContainText('600/minute for production keys, 60/minute for sandbox keys')
  await expect(page.getByTestId('keys-empty')).toBeVisible()
  await expect(page.getByTestId('audit-empty')).toBeVisible()

  // Nothing is sent when the form is incomplete.
  await page.getByTestId('key-create').click()
  await expect(page.getByTestId('key-form-error')).toHaveText('Give the key a name.')
  await page.getByLabel('Key name').fill('Reporting key')
  await page.getByTestId('key-create').click()
  await expect(page.getByTestId('key-form-error')).toHaveText('Pick at least one entity the key may read.')
  expect(seen.filter((s) => s.method === 'POST')).toHaveLength(0)

  await page.getByTestId('key-scope').first().check() // Invoice
  await page.getByTestId('key-create').click()
  const secret = page.getByTestId('secret-panel')
  await expect(secret).toBeVisible()
  await expect(secret.getByTestId('secret-value')).toHaveText('pk_sand_ab12_THE-ONLY-TIME-YOU-SEE-THIS')
  const made = seen.find((s) => s.method === 'POST' && s.path === '/platform/keys')!
  expect(made.body).toEqual({ name: 'Reporting key', scopes: ['Invoice'], environment: 'sandbox' })
  const row = page.getByTestId('key-row')
  await expect(row).toHaveCount(1)
  await expect(row).toContainText('Reporting key')
  await expect(row).toContainText('pk_sand_ab12')
  await expect(row).toHaveAttribute('data-status', 'active')
  await expect(page.getByTestId('audit-row')).toContainText('key.create')
  await expectAxeClean(page, 'api keys with the secret shown')

  // Dismissing drops the secret for good; the list never shows the full key.
  await page.getByTestId('secret-dismiss').click()
  await expect(secret).toHaveCount(0)
  await expect(page.getByText('THE-ONLY-TIME-YOU-SEE-THIS')).toHaveCount(0)

  // Revoke asks first; "Keep it" changes nothing.
  await page.getByRole('button', { name: 'Revoke key Reporting key' }).click()
  await page.getByRole('button', { name: 'Keep it' }).click()
  expect(seen.some((s) => s.path.endsWith('/revoke'))).toBe(false)
  await page.getByRole('button', { name: 'Revoke key Reporting key' }).click()
  await page.getByTestId('revoke-confirm').click()
  await expect(page.getByTestId('key-note')).toHaveText('Key revoked.')
  await expect(row).toHaveAttribute('data-status', 'revoked')
  await expect(page.getByTestId('revoke')).toHaveCount(0)
  await expect(page.getByTestId('audit-row').filter({ hasText: 'key.revoke' })).toHaveCount(1)
  expect(seen.every((s) => s.previewToken !== undefined)).toBe(true)

  await expectAxeClean(page, 'api keys page')
  watch.assertNone()
})
