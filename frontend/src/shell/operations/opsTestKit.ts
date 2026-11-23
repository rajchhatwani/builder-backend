import { vi } from 'vitest'

export const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })
export const empty = (status = 204) => new Response(null, { status })
export type Rec = { m: string; url: string; body?: unknown }

/** A fake generated-project API: `over` answers first; unanswered calls get `dflt` (or 404). Records every call. */
export function fakeApi(over: (m: string, url: string, body: unknown) => Response | Promise<Response> | undefined, dflt: (m: string, url: string) => Response = () => json({}, 404)) {
  const calls: Rec[] = []
  const f = vi.fn(async (url: string, init: RequestInit) => {
    const m = init.method ?? 'GET'
    const body = init.body ? JSON.parse(init.body as string) : undefined
    calls.push({ m, url, body })
    return (await over(m, url, body)) ?? dflt(m, url)
  }) as unknown as typeof fetch
  const to = (m: string, frag: string) => calls.filter((c) => c.m === m && c.url.includes(frag))
  return { f, calls, to }
}
