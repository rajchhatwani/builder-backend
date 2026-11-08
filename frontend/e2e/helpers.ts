import { execFileSync } from 'node:child_process'
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

/** Test setup only: marks an account's e-mail as confirmed straight in the throwaway e2e database (there is no
 *  test bypass in the product). The container is the one stack.sh starts. */
export function markEmailVerified(email: string): void {
  const sql = `update platform_users set email_verified_at = now() where email = '${email.toLowerCase().replace(/'/g, "''")}'`
  execFileSync('docker', ['exec', 'bb-e2e-pg', 'psql', '-U', 'builder', '-d', 'builder', '-v', 'ON_ERROR_STOP=1', '-c', sql], { stdio: 'pipe' })
}

/** Test setup only: the e2e stack has no scripted model, so a run that is waiting on a person is seeded straight
 *  in the throwaway database (same escape hatch as markEmailVerified): the run (made through the API) is moved to
 *  awaiting_approval and one pending approval is inserted for it. Returns the approval id. */
export function seedPendingApproval(runId: string, projectId: string, kind: 'A' | 'B' | 'C' | 'D' | 'E', subject: string, payload: Record<string, unknown>, riskFlags: string[] = []): string {
  const lit = (v: unknown) => `'${JSON.stringify(v).replace(/'/g, "''")}'::jsonb`
  const uuid = (v: string) => { if (!/^[0-9a-f-]{36}$/i.test(v)) throw new Error('not a uuid'); return `'${v}'` }
  const sql = `update ai_runs set state='awaiting_approval', phase='build' where id=${uuid(runId)};` +
    `insert into ai_approvals (id, run_id, project_id, kind, subject, payload, risk_flags, state, bound_spec_hash, expires_at, created_at) ` +
    `values (gen_random_uuid(), ${uuid(runId)}, ${uuid(projectId)}, '${kind}', '${subject.replace(/'/g, "''")}', ${lit(payload)}, ${lit(riskFlags)}, 'pending', '${'0'.repeat(64)}', now() + interval '1 day', now()) returning id`
  const out = execFileSync('docker', ['exec', 'bb-e2e-pg', 'psql', '-U', 'builder', '-d', 'builder', '-v', 'ON_ERROR_STOP=1', '-At', '-c', sql], { stdio: 'pipe' }).toString()
  const id = out.split('\n').find((l) => /^[0-9a-f-]{36}$/i.test(l.trim()))
  if (!id) throw new Error(`approval not seeded: ${out}`)
  return id.trim()
}

/** Create a customer account through the API (setup only; the UI sign-up journey is separate).
 *  Register answers 202 without a session, so: register, mark verified in the database, then log in. */
export async function registerViaApi(request: APIRequestContext, email = uniqueEmail()) {
  const r = await request.post(`${API}/account/register`, {
    data: { email, password: PASSWORD, name: 'E2E User' },
    headers: H,
  })
  expect(r.status(), await r.text()).toBe(202)
  markEmailVerified(email)
  const login = await request.post(`${API}/account/login`, { data: { email, password: PASSWORD }, headers: H })
  expect(login.status(), await login.text()).toBe(200)
  const body = await login.json()
  expect(body.mfa_required, 'a fresh account has no second step').toBeFalsy() // LoginResult is a session or an MFA challenge
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

/** The neutral invoice-approval example (one entity, one state machine, auth on). */
export async function importInvoiceFlow(api: Api, projectId: string) {
  const { readFileSync } = await import('node:fs')
  const { fileURLToPath } = await import('node:url')
  const dir = fileURLToPath(new URL('../../tests/fixtures/specs/', import.meta.url))
  const r = await api.put(`/projects/${projectId}/spec`, JSON.parse(readFileSync(dir + 'flow_invoices.json', 'utf8')))
  expect(r.status(), await r.text()).toBe(200)
}

/** The invoice example, then two guards that do not compile (unknown field `bogus_field`, dangling `amount <= `),
 *  written through the behaviour API (which accepts work in progress; PUT /spec refuses them). */
export async function importBrokenInvoiceFlow(api: Api, projectId: string) {
  await importInvoiceFlow(api, projectId)
  const cur = await (await api.get(`/projects/${projectId}/behavior/state-machines`)).json()
  const machines = cur.state_machines
  const ts = machines[0].transitions
  ts.find((t: { name: string }) => t.name === 'approve').when = 'bogus_field > 1'
  ts.find((t: { name: string }) => t.name === 'auto_approve').when = 'amount <= '
  const r = await api.put(`/projects/${projectId}/behavior/state-machines`, { state_machines: machines, expected_version: cur.version })
  expect(r.status(), await r.text()).toBe(200)
}
