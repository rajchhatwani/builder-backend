/** Shared by the Cycle-5 page specs: the generated project's API is mocked on the build-time preview origin with page.route
 *  (no generated app needed). Needs the web build made with VITE_PREVIEW_API_ORIGIN=http://localhost:8799 (stack.sh default;
 *  E2E_PREVIEW_ORIGIN overrides). Not a spec file (testMatch is *.spec.ts). */
import type { Page } from '@playwright/test'

export const WEB = process.env.E2E_WEB_PORT ?? '5199'
export const PREVIEW = process.env.E2E_PREVIEW_ORIGIN ?? 'http://localhost:8799'
export const V2_STATE = { cookies: [], origins: [{ origin: `http://localhost:${WEB}`, localStorage: [{ name: 'ui.shell', value: 'v2' }] }] }
const CORS = { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': '*' }

export interface Seen { method: string; path: string; search: string; body: Record<string, unknown> | null; auth: string | undefined }
export interface Answer { status?: number; json: unknown }

/** Answers every request to the preview origin (CORS preflight included). `handler` returns undefined for "not mine" (-> 404). */
export async function mockPreview(page: Page, handler: (r: Seen) => Answer | undefined): Promise<Seen[]> {
  const seen: Seen[] = []
  await page.route(`${PREVIEW}/**`, async (route) => {
    const req = route.request()
    if (req.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: CORS })
    const u = new URL(req.url())
    const raw = req.postData()
    let body: Record<string, unknown> | null = null
    try { body = raw ? (JSON.parse(raw) as Record<string, unknown>) : null } catch { body = null }
    const s: Seen = { method: req.method(), path: u.pathname, search: u.search, body, auth: req.headers().authorization }
    seen.push(s)
    const a = handler(s) ?? { status: 404, json: { code: 'not_found', message: 'no such mock' } }
    return route.fulfill({ status: a.status ?? 200, headers: CORS, contentType: 'application/json', body: JSON.stringify(a.json) })
  })
  return seen
}
