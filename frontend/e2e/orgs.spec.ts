import { expect, test } from '@playwright/test'
import { API, registerViaApi, setPlanAsAdmin, signInViaUi, signedInUser, watchProblems } from './helpers'

const TABS = [
  ['People', ''],
  ['Invites', '/invites'],
  ['Projects', '/projects'],
  ['Plan', '/plan'],
  ['Audit log', '/audit'],
  ['SSO & SCIM', '/sso'],
  ['Security', '/policies'],
] as const

test.describe('organizations', () => {
  test('console tabs load and the deep links hold', async ({ page, request }) => {
    const api = await signedInUser(page, request)
    const slug = `acme-${Date.now()}`
    expect((await api.post('/orgs', { name: 'Acme Journey', slug })).status()).toBe(201)
    const watch = watchProblems(page)
    for (const [label, path] of TABS) {
      await page.goto(`/#/org/${slug}${path}`)
      await expect(page.getByRole('heading', { name: /Acme Journey/ }).first()).toBeVisible()
      await expect(page.getByRole('tab', { name: label, exact: true })).toHaveAttribute('aria-selected', 'true')
      await expect(page).toHaveURL(new RegExp(`#/org/${slug}${path}$`))
    }
    watch.assertNone()
  })

  test('a member invited by link can accept and then sees the org', async ({ page, request }) => {
    const owner = await registerViaApi(request)
    const slug = `inv-${Date.now()}`
    const created = await owner.post('/orgs', { name: 'Invite Journey', slug })
    expect(created.status()).toBe(201)
    await setPlanAsAdmin(request, (await created.json()).id)
    const bob = await registerViaApi(request)
    const invite = await owner.post(`/orgs/${slug}/invitations`, { email: bob.email, role: 'member' })
    expect(invite.status(), await invite.text()).toBe(201)
    const { token } = await invite.json()

    await signInViaUi(page, bob.email)
    await page.goto(`/#/invite/${token}`)
    const accepted = page.waitForResponse((r) => r.url().includes('/orgs/invitations/accept') && r.ok())
    await page.getByRole('button', { name: 'Accept invitation' }).click()
    await accepted
    await page.goto(`/#/org/${slug}`)
    await expect(page.getByRole('heading', { name: /Invite Journey/ }).first()).toBeVisible()
    const members = await (await owner.get(`/orgs/${slug}/members`)).json()
    expect(JSON.stringify(members)).toContain(bob.email)
  })

  test('a malformed invitation e-mail is refused (F-3)', async ({ request }) => {
    const owner = await registerViaApi(request)
    const slug = `bad-${Date.now()}`
    await owner.post('/orgs', { name: 'Bad Invite', slug })
    const r = await owner.post(`/orgs/${slug}/invitations`, { email: 'not-an-email', role: 'member' })
    expect(r.status()).toBe(422)
  })

  test('the People table stays usable at 375px (F-8) and member notice names owners (C-1)', async ({ page, request }) => {
    const owner = await registerViaApi(request)
    const slug = `mob-${Date.now()}`
    const created = await owner.post('/orgs', { name: 'Mobile Journey', slug })
    await setPlanAsAdmin(request, (await created.json()).id)
    const bob = await registerViaApi(request)
    const invite = await owner.post(`/orgs/${slug}/invitations`, { email: bob.email, role: 'member' })
    await request.post(`${API}/orgs/invitations/accept`, {
      data: { token: (await invite.json()).token },
      headers: { 'X-Requested-With': 'builder', Authorization: `Bearer ${bob.token}` },
    })

    await signInViaUi(page, owner.email)
    await page.setViewportSize({ width: 375, height: 800 })
    await page.goto(`/#/org/${slug}`)
    const box = await page.locator('.table-scroll select').first().boundingBox()
    expect(box?.width ?? 0).toBeGreaterThanOrEqual(90) // "A⌄" clipping was ~20px
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
    expect(overflow, 'no page-level horizontal overflow').toBe(false)

    // A plain member sees who to ask, by name and address, with a clean sentence.
    await page.getByRole('button', { name: 'Sign out' }).click()
    await signInViaUi(page, bob.email)
    await page.goto(`/#/org/${slug}/policies`)
    const notice = page.getByRole('alert').filter({ hasText: 'Only owners and admins' })
    await expect(notice).toContainText(owner.email)
    await expect(notice).not.toContainText(/Ask\s{2,}/)
  })
})
