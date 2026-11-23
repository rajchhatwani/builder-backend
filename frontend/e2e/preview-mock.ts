/** Shared by the Cycle-5 page specs: the generated project's API is mocked on the build-time preview origin with page.route
 *  (no generated app needed). Needs the web build made with VITE_PREVIEW_API_ORIGIN=http://localhost:8799 (stack.sh default;
 *  E2E_PREVIEW_ORIGIN overrides). Not a spec file (testMatch is *.spec.ts). */
import { expect, type Page } from '@playwright/test'
import { API } from './helpers'

export const PREVIEW = process.env.E2E_PREVIEW_ORIGIN ?? 'http://localhost:8799'
const CORS = { 'access-control-allow-origin': '*', 'access-control-allow-headers': 'authorization, content-type, x-preview-token, accept', 'access-control-allow-methods': '*' }

export interface Seen { method: string; path: string; search: string; body: Record<string, unknown> | null; auth: string | undefined; previewToken: string | undefined }
export interface Answer { status?: number; json?: unknown; /** Plain-text body (a patch, a CSV) instead of json. */ text?: string; contentType?: string }

/** Answers every request to the preview origin (CORS preflight included). `handler` returns undefined for "not mine" (-> 404). */
export async function mockPreview(page: Page, handler: (r: Seen) => Answer | undefined, opts: { strip?: string; record?: (r: Seen) => boolean } = {}): Promise<Seen[]> {
  const seen: Seen[] = []
  await page.route(`${PREVIEW}/**`, async (route) => {
    const req = route.request()
    if (req.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: CORS })
    const u = new URL(req.url())
    const raw = req.postData()
    let body: Record<string, unknown> | null = null
    try { body = raw ? (JSON.parse(raw) as Record<string, unknown>) : null } catch { body = null }
    const path = opts.strip && u.pathname.startsWith(opts.strip) ? u.pathname.slice(opts.strip.length) || '/' : u.pathname
    const s: Seen = { method: req.method(), path, search: u.search, body, auth: req.headers().authorization, previewToken: req.headers()['x-preview-token'] }
    if (!opts.record || opts.record(s)) seen.push(s)
    const a = handler(s) ?? { status: 404, json: { code: 'not_found', message: 'no such mock' } }
    return route.fulfill({ status: a.status ?? 200, headers: CORS, contentType: a.contentType ?? (a.text === undefined ? 'application/json' : 'text/plain'), body: a.text ?? JSON.stringify(a.json) })
  })
  return seen
}

/** Answers builder-API requests whose URL matches `urlRe` (credentialed CORS included) for a project that exists in the real API but whose
 *  answers the journey needs to control. `handler` returns undefined to let the request through to the real API. */
export async function mockBuilder(page: Page, urlRe: RegExp, handler: (r: Seen) => Answer | undefined): Promise<Seen[]> {
  const seen: Seen[] = []
  await page.route(urlRe, async (route) => {
    const req = route.request()
    if (req.method() === 'OPTIONS') return route.fallback()
    const u = new URL(req.url())
    const raw = req.postData()
    let body: Record<string, unknown> | null = null
    try { body = raw ? (JSON.parse(raw) as Record<string, unknown>) : null } catch { body = null }
    const s: Seen = { method: req.method(), path: u.pathname, search: u.search, body, auth: req.headers().authorization, previewToken: undefined }
    const a = handler(s)
    if (!a) return route.fallback()
    seen.push(s)
    const headers = { 'access-control-allow-origin': req.headers().origin ?? '*', 'access-control-allow-credentials': 'true', vary: 'Origin' }
    return route.fulfill({ status: a.status ?? 200, headers, contentType: a.contentType ?? (a.text === undefined ? 'application/json' : 'text/plain'), body: a.text ?? JSON.stringify(a.json) })
  })
  return seen
}

/** What the mocked preview session hands out. The page must send exactly these (see Seen.auth / Seen.previewToken). */
export const SESSION = {
  previewId: '11111111-2222-4333-8444-555555555555',
  previewToken: 'e2e-preview-access-token',
  jwt: 'e2e-preview-app-jwt',
  email: 'owner@preview.test',
  password: 'Preview-pass-123',
} as const
/** Bearer value a request made by a signed-in preview page carries. */
export const BEARER = `Bearer ${SESSION.jwt}`

export interface SessionOptions {
  /** Preview state the builder API reports (default running). */
  state?: 'running' | 'sleeping'
  /** The list of previews is empty (the page offers "Start a preview"). */
  none?: boolean
}

/** Mocks everything usePreviewSession needs, for a project that exists in the real builder API:
 *   GET  <API>/projects/<id>/previews                       -> one live preview (url_path maps onto PREVIEW), others pass through
 *   POST <API>/projects/<id>/previews/<pid>/rotate-token    -> SESSION.previewToken
 *   POST <PREVIEW>/previews/<pid>/auth/login                -> SESSION.jwt for SESSION.email / SESSION.password (not recorded in the returned list)
 *  and every other request to the generated app through `handler`, with the "/previews/<pid>" prefix removed from the path (so
 *  handlers match "/ledger/accounts"). App requests missing the preview token or the signed-in bearer get the 401 the real stack gives.
 *  Returns the recorded app requests (login excluded). Use signInPreview() to go through the gate. */
export async function mockPreviewSession(page: Page, projectId: string, handler: (r: Seen) => Answer | undefined, opts: SessionOptions = {}): Promise<Seen[]> {
  const pid = SESSION.previewId
  const now = Date.now()
  const row = {
    id: pid, project_id: projectId, workspace_id: null, state: opts.state ?? 'running', spec_hash: 'e2e', url_path: `/previews/${pid}/`, error: null,
    created_at: new Date(now - 60_000).toISOString(), last_request_at: new Date(now).toISOString(), expires_at: new Date(now + 3_600_000).toISOString(), limits: {}, is_preview: true,
  }
  // route.fetch() goes to the real builder API (CORS headers and all); only the body and status are replaced.
  await page.route(new RegExp(`^${API}/projects/${projectId}/previews$`), async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    const res = await route.fetch()
    return route.fulfill({ response: res, status: 200, json: opts.none ? [] : [row] })
  })
  await page.route(new RegExp(`^${API}/projects/${projectId}/previews/${pid}/rotate-token$`), async (route) => {
    if (route.request().method() !== 'POST') return route.fallback()
    const res = await route.fetch()
    return route.fulfill({ response: res, status: 200, json: { ...row, token: SESSION.previewToken } })
  })
  const prefix = `/previews/${pid}`
  return mockPreview(page, (r) => {
    if (r.previewToken !== SESSION.previewToken) return { status: 401, json: { detail: 'Invalid preview token' } }
    if (r.method === 'POST' && r.path === '/auth/login') {
      const b = r.body as { email?: string; password?: string } | null
      if (b?.email === SESSION.email && b?.password === SESSION.password) return { json: { access_token: SESSION.jwt, token_type: 'bearer' } }
      return { status: 401, json: { detail: 'Invalid email or password' } }
    }
    if (r.auth !== BEARER) return { status: 401, json: { detail: 'Not authenticated' } }
    return handler(r)
  }, { strip: prefix, record: (r) => !(r.method === 'POST' && r.path === '/auth/login') })
}

/** Goes through PreviewSessionGate's sign-in form with the mocked account and waits for the page behind it. */
export async function signInPreview(page: Page): Promise<void> {
  await expect(page.getByTestId('preview-signin')).toBeVisible()
  await page.getByTestId('preview-email').fill(SESSION.email)
  await page.getByTestId('preview-password').fill(SESSION.password)
  await page.getByTestId('preview-signin-btn').click()
  await expect(page.getByTestId('preview-signin')).toHaveCount(0)
}
