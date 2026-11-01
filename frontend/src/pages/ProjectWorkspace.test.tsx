import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ProjectWorkspace } from './ProjectWorkspace'
import { UiProvider } from '../components/Ui'
import { setAccessToken } from '../api/session'

;vi.mock('../components/AuthProvider', () => {
  const user = { id: 'u1', email: 'a@b.c', name: 'A', is_platform_admin: false }
  const api = { state: { status: 'user', user }, signOut: async () => {}, viewing: null, setViewing() {}, setUser() {} }
  return { useAuth: () => api, useUser: () => user, AuthProvider: ({ children }: { children: unknown }) => children }
})

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const project = { id: 'p1', name: 'Demo', slug: 'demo', organization_id: null, role: 'owner' }
const page = { items: [], total: 0 }

type Handler = (path: string) => Response | Promise<Response>
let handler: Handler
let root: Root
let host: HTMLElement

function route(overrides: Record<string, () => Response> = {}): Handler {
  return (path) => {
    for (const [frag, make] of Object.entries(overrides)) if (path.endsWith(frag)) return make()
    if (path.endsWith('/projects/p1')) return json(200, project)
    if (/(entities|relations|roles|generations)/.test(path)) return json(200, page)
    return json(404, { code: 'not_found', message: 'nope', details: [] })
  }
}

async function mount() {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  await act(async () => {
    root.render(
      <QueryClientProvider client={qc}>
        <UiProvider>
          <ProjectWorkspace projectId="p1" section="overview" />
        </UiProvider>
      </QueryClientProvider>,
    )
  })
  await act(async () => {
    await new Promise((r) => setTimeout(r, 20))
  })
}

beforeEach(() => {
  vi.stubGlobal('matchMedia', (q: string) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
  setAccessToken('app', 'tok')
  vi.stubGlobal('fetch', vi.fn(async (url: string) => handler(String(url))))
})
afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
  vi.unstubAllGlobals()
  setAccessToken('app', null)
})

describe('ProjectWorkspace load failures', () => {
  it('a 404 on the project is "can\'t find this project"', async () => {
    handler = route({ '/projects/p1': () => json(404, { code: 'not_found', message: 'x', details: [] }) })
    await mount()
    expect(host.textContent).toContain("We can't find this project")
    expect(host.querySelector('[data-testid="load-error"]')).toBeNull()
  })

  it('a 502 with an HTML body shows an error banner with Retry, not "missing"; retry recovers', async () => {
    let down = true
    handler = route({
      '/projects/p1': () => (down ? new Response('<html>Bad Gateway</html>', { status: 502 }) : json(200, project)),
    })
    await mount()
    expect(host.textContent).not.toContain("We can't find this project")
    const banner = host.querySelector('[data-testid="load-error"]')
    expect(banner).not.toBeNull()
    const retry = [...host.querySelectorAll('button')].find((b) => b.textContent === 'Retry')!
    expect(retry).toBeTruthy()
    down = false
    await act(async () => {
      retry.click()
      await new Promise((r) => setTimeout(r, 20))
    })
    expect(host.querySelector('[data-testid="load-error"]')).toBeNull()
    expect(host.textContent).not.toContain("We can't find this project")
    expect(host.textContent).toContain('Demo')
  })

  it('a network error on the project is an error banner, not "missing"', async () => {
    handler = () => {
      throw new TypeError('Failed to fetch')
    }
    await mount()
    expect(host.querySelector('[data-testid="load-error"]')).not.toBeNull()
    expect(host.textContent).not.toContain("We can't find this project")
  })

  it('a failing secondary request (entities 500, relations non-JSON) still renders the page', async () => {
    handler = route({
      '/entities?limit=200&offset=0': () => json(500, { code: 'boom', message: 'x', details: [] }),
      '/relations?limit=200&offset=0': () => new Response('oops', { status: 503 }),
    })
    await mount()
    expect(host.querySelector('[data-testid="load-error"]')).toBeNull()
    expect(host.textContent).not.toContain("We can't find this project")
    expect(host.textContent).toContain('Demo')
  })
})
