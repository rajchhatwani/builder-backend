import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const email = 'reader@example.test'
const user = { id: 'user', email, email_verified_at: '2026-11-20T12:00:00Z', platform_role: 'customer' }
const organization = { id: 'library', name: 'City Library', slug: 'city-library' }
const invitation = {
  id: 'invite-id', organization_name: organization.name, organization_slug: organization.slug,
  role: 'member', status: 'pending', created_at: '2026-11-21T12:00:00Z', expires_at: '2026-12-05T12:00:00Z',
}
const token = 'city-library-email-link'
const cases = ['login', 'signin', 'signup', 'verify-email', 'sso-complete', 'invitations'] as const
type Screen = typeof cases[number]
type State = 'normal' | 'loading' | 'empty' | 'error'
const screenshots: Record<State, (page: Page, screen: Screen) => Promise<void>> = {
  normal: (page, screen) => expect(page).toHaveScreenshot(`${screen}-normal.png`, { fullPage: true }),
  loading: (page, screen) => expect(page).toHaveScreenshot(`${screen}-loading.png`, { fullPage: true }),
  empty: (page, screen) => expect(page).toHaveScreenshot(`${screen}-empty.png`, { fullPage: true }),
  error: (page, screen) => expect(page).toHaveScreenshot(`${screen}-error.png`, { fullPage: true }),
}
const headers = {
  'access-control-allow-origin': 'http://localhost:5299',
  'access-control-allow-credentials': 'true',
  'access-control-allow-methods': 'GET, POST, OPTIONS',
  'access-control-allow-headers': 'content-type, authorization, x-requested-with',
}

async function mock(page: Page, screen: Screen, state: State, options: { withLink?: boolean; enrollment?: boolean; unverified?: boolean } = {}) {
  await page.addInitScript(() => localStorage.setItem('v2-language', 'en'))
  await page.clock.setFixedTime(new Date('2026-11-25T12:00:00Z'))
  let release = () => {}
  const delay = new Promise<void>(resolve => { release = resolve })
  const bodies: Record<string, unknown[]> = {}
  let signedIn = screen === 'invitations' && !options.withLink || screen === 'sso-complete' && state === 'normal'
  let joined = false
  const account = options.unverified ? { ...user, email_verified_at: null } : user
  await page.route(url => url.port === '8000', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers })
    const send = (json: unknown, status = 200) => route.fulfill({ status, headers, json })
    const fail = (code: string, status: number) => send({ code, message: code, details: [] }, status)
    if (request.postData()) (bodies[path] ??= []).push(request.postDataJSON())

    if (path === '/account/refresh') {
      if (screen === 'sso-complete' && state === 'loading') await delay
      if (screen === 'sso-complete' && state === 'error') return fail('fixture_unavailable', 503)
      return signedIn ? send({ access_token: 'fixture-session' }) : fail('invalid_refresh_token', 401)
    }
    if (path === '/account/me') return send(joined ? user : account)
    if (path === '/account/login/discover') {
      if (state === 'loading') await delay
      if (state === 'error') return fail('fixture_unavailable', 503)
      if (screen === 'login') return send({
        method: 'sso', login_url: 'http://localhost:8000/sso/city-library/login', organization_name: organization.name,
      })
      return send({ method: 'password' })
    }
    if (path === '/account/login') {
      if (options.enrollment) return send({
        mfa_required: true, enrollment_required: true, mfa_token: 'fixture-enrollment', expires_in: 300, methods: ['totp'],
      })
      signedIn = true
      return send({ user: account, access_token: 'fixture-session' })
    }
    if (path === '/account/login/mfa/setup') return send({
      secret: 'JBSWY3DPEHPK3PXP', otpauth_uri: 'otpauth://totp/Library?secret=JBSWY3DPEHPK3PXP',
    })
    if (path === '/account/login/mfa/enable') {
      signedIn = true
      return send({ user, access_token: 'fixture-session', recovery_codes: ['ABCD-EFGH', 'JKLM-NPQR'] })
    }
    if (path === '/account/register') {
      if (state === 'loading') await delay
      if (state === 'error') return fail('signup_closed', 403)
      return send({ status: 'verification_sent' }, 202)
    }
    if (path === '/account/verify-email') {
      if (state === 'loading') await delay
      if (state === 'error') return fail('invalid_token', 400)
      return send(user)
    }
    if (path === '/account/verify-email/resend') return send({ status: 'verification_sent' }, 202)
    if (path === '/orgs/invitations/pending') {
      if (screen === 'invitations' && state === 'loading') await delay
      if (screen === 'invitations' && state === 'error') return fail('fixture_unavailable', 503)
      const items = screen === 'invitations' && state === 'normal' && !joined ? [invitation] : []
      return send({ items, total: items.length, limit: items.length, offset: 0 })
    }
    if (path === '/orgs') return send({ items: joined ? [organization] : [], total: Number(joined) })
    if (path === '/orgs/city-library') return send(organization)
    if (path === '/orgs/invitations/accept' || path === '/orgs/invitations/invite-id/accept') {
      joined = true
      return send(organization)
    }
    return fail('fixture_missing', 404)
  })
  return { release, bodies }
}

async function enterEmail(page: Page) {
  await page.getByLabel('Email', { exact: true }).fill(email)
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
}

for (const screen of cases) {
  for (const state of ['normal', 'loading', 'empty', 'error'] as const) {
    test(`${screen} ${state}`, async ({ page }) => {
      const fixture = await mock(page, screen, state)
      try {
        if (screen === 'login' || screen === 'signin') {
          await page.goto('/' + screen)
          if (state !== 'empty') await enterEmail(page)
          if (state === 'empty') await expect(page.getByLabel('Email', { exact: true })).toBeVisible()
          if (state === 'loading') await expect(page.getByRole('status', { name: 'Please wait…' })).toBeVisible()
          if (state === 'error') await expect(page.getByRole('alert')).toContainText("couldn't complete")
          if (state === 'normal' && screen === 'login') await expect(page.getByRole('button', { name: 'Continue with City Library SSO' })).toBeVisible()
          if (state === 'normal' && screen === 'signin') await expect(page.getByLabel('Password', { exact: true })).toBeVisible()
        } else if (screen === 'signup') {
          await page.goto('/signup')
          await expect(page.getByRole('button', { name: 'Create account' })).toBeVisible()
          if (state !== 'empty') {
            await page.getByLabel('Name', { exact: true }).fill('Library Reader')
            await page.getByLabel('Email', { exact: true }).fill(email)
            await page.getByLabel('Password', { exact: true }).fill('Dancing-tables-256')
            await page.getByRole('button', { name: 'Create account' }).click()
          }
          if (state === 'loading') await expect(page.getByRole('button', { name: /Please wait/ })).toBeDisabled()
          if (state === 'normal') await expect(page.getByTestId('check-inbox')).toBeVisible()
          if (state === 'error') await expect(page.getByText('Sign-up is closed. Ask an administrator.')).toBeVisible()
        } else if (screen === 'verify-email') {
          await page.goto(state === 'empty' ? '/verify-email' : '/verify-email?token=' + token)
          if (state === 'normal') await expect(page.getByTestId('verify-ok')).toBeVisible()
          if (state === 'loading') await expect(page.getByRole('status', { name: 'Confirming…' })).toBeVisible()
          if (state === 'error' || state === 'empty') await expect(page.getByTestId('verify-bad')).toBeVisible()
          await expect(page).toHaveURL(/\/verify-email$/)
        } else if (screen === 'sso-complete') {
          await page.goto('/#/sso/complete')
          if (state === 'normal') await expect(page.getByRole('heading', { name: 'Projects', level: 1 })).toBeVisible()
          if (state === 'loading') await expect(page.getByRole('status', { name: 'Signing you in…' })).toBeVisible()
          if (state === 'empty') await expect(page.getByText("The SSO sign-in didn't finish. Try again.")).toBeVisible()
          if (state === 'error') await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
        } else {
          await page.goto('/invitations')
          if (state === 'normal') await expect(page.getByRole('button', { name: 'Accept invitation from City Library' })).toBeVisible()
          if (state === 'loading') await expect(page.getByRole('status', { name: 'Loading invitations…' })).toBeVisible()
          if (state === 'empty') await expect(page.getByText(`No open invitations for ${email}.`)).toBeVisible()
          if (state === 'error') await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
        }

        await page.evaluate(() => document.fonts.ready.then(() => undefined))
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(await page.evaluate(() => window.innerWidth))
        const results = await new AxeBuilder({ page }).analyze()
        expect(results.violations.map(({ id, nodes }) => ({ id, targets: nodes.map(node => node.target) }))).toEqual([])
        await screenshots[state](page, screen)
      } finally {
        fixture.release()
      }
    })
  }
}

test('keeps an issued invitation through sign-in and lets the matching unverified account accept it', async ({ page }) => {
  const fixture = await mock(page, 'invitations', 'normal', { withLink: true, unverified: true })
  await page.goto('/#/invite/' + token)
  await enterEmail(page)
  await page.getByLabel('Password', { exact: true }).fill('correct password')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByText(/Confirm your email to see your pending invitations/)).toBeVisible()
  await page.getByRole('button', { name: 'Accept invitation', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'City Library' })).toBeVisible()
  await expect(page).toHaveURL(/\/org\/city-library$/)
  expect(fixture.bodies['/orgs/invitations/accept']).toEqual([{ token }])
})

test('loads the staff QR once and waits for recovery-code acknowledgement before completing sign-in', async ({ page, request }) => {
  // Vite can reuse an optimizer cache from before the QR adapter existed. Finish
  // optimizing its dependency before opening a page that holds an MFA challenge.
  const adapter = await request.get('/src/v2/features/entry/components/QrImage.tsx')
  await expect(adapter).toBeOK()
  const optimizedQr = (await adapter.text()).match(/"(\/[^"]*\/qrcode\.js)\?v=[^"]+"/)?.[1]
  if (!optimizedQr) throw new Error('Vite did not resolve the QR adapter’s optimized dependency')
  // The optimizer can invalidate the first request while it updates the cache.
  await expect.poll(async () => (await request.get(optimizedQr)).status()).toBe(200)

  const fixture = await mock(page, 'signin', 'normal', { enrollment: true })
  await page.goto('/signin')
  await enterEmail(page)
  await page.getByLabel('Password', { exact: true }).fill('correct password')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('img', { name: 'QR code for your authenticator app' })).toBeVisible()
  await page.getByLabel('6-digit code', { exact: true }).fill('123456')
  await page.getByRole('button', { name: 'Turn on and sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Two-factor is on' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Continue', exact: true })).toBeDisabled()
  await page.getByRole('checkbox', { name: 'I saved my recovery codes' }).check()
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(page).toHaveURL(/\/projects$/)
  expect(fixture.bodies['/account/login/mfa/setup']).toHaveLength(1)
})
