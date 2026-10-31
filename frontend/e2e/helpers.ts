import { expect, type APIRequestContext, type Page } from '@playwright/test'

export const API = `http://localhost:${process.env.E2E_API_PORT ?? '8765'}`
export const PASSWORD = 'Correct-horse-battery-9!'
export const ADMIN = { email: 'e2e-admin@example.com', password: 'Quartz-Lantern-Velvet-47' }
const H = { 'X-Requested-With': 'builder' }

let counter = 0
export function uniqueEmail(tag = 'u'): string {
  counter += 1
  return `${tag}-${Date.now()}-${counter}-${Math.floor(Math.random() * 1e6)}@example.com`
}

/** Create a customer account through the API (setup only; the UI sign-up journey is separate). */
export async function registerViaApi(request: APIRequestContext, email = uniqueEmail()) {
  const r = await request.post(`${API}/account/register`, {
    data: { email, password: PASSWORD, name: 'E2E User' },
    headers: H,
  })
  expect(r.status(), await r.text()).toBe(201)
  const body = await r.json()
  const token: string = body.access_token
  const auth = { ...H, Authorization: `Bearer ${token}` }
  return {
    email,
    token,
    post: (path: string, data?: unknown) => request.post(`${API}${path}`, { data, headers: auth }),
    get: (path: string) => request.get(`${API}${path}`, { headers: auth }),
    patch: (path: string, data?: unknown) => request.patch(`${API}${path}`, { data, headers: auth }),
    put: (path: string, data?: unknown) => request.put(`${API}${path}`, { data, headers: auth }),
  }
}
export type Api = Awaited<ReturnType<typeof registerViaApi>>

export async function signInViaUi(page: Page, email: string, password = PASSWORD) {
  await page.goto('/#/')
  await page.getByRole('textbox', { name: 'Email' }).fill(email)
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible()
}

/** A signed-in customer in the browser plus an API handle for setup. */
export async function signedInUser(page: Page, request: APIRequestContext) {
  const api = await registerViaApi(request)
  await signInViaUi(page, api.email)
  return api
}

export async function createProjectViaApi(api: Api, name: string): Promise<string> {
  const r = await api.post('/projects', { name })
  expect(r.status(), await r.text()).toBe(201)
  return (await r.json()).id
}

export const SECTION_IDS = [
  'overview', 'model', 'auth', 'keycloak', 'payments', 'storage',
  'access', 'observability', 'deployment', 'documents', 'integrations', 'generate',
] as const

/** Fail on unexpected console errors / failed API calls while a journey runs. */
export function watchProblems(page: Page, ignore: RegExp[] = []) {
  const problems: string[] = []
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`))
  page.on('response', (r) => {
    const url = r.url()
    if (url.startsWith(API) && r.status() >= 500) problems.push(`${r.status()} ${url}`)
  })
  return {
    problems,
    assertNone() {
      expect(problems.filter((p) => !ignore.some((re) => re.test(p)))).toEqual([])
    },
  }
}

/** Operator actions the UI journeys need as setup (e.g. a plan with more than one seat). */
export async function setPlanAsAdmin(request: APIRequestContext, orgId: string, planId = 'business') {
  const login = await request.post(`${API}/admin/login`, { data: ADMIN, headers: H })
  expect(login.status(), await login.text()).toBe(200)
  const { access_token } = await login.json()
  const r = await request.patch(`${API}/admin/organizations/${orgId}/plan`, {
    data: { plan_id: planId, reason: 'e2e journey setup' },
    headers: { ...H, Authorization: `Bearer ${access_token}` },
  })
  expect(r.status(), await r.text()).toBe(200)
}
