import axe from 'axe-core'
import { act, createElement } from 'react'
import { describe, expect, it } from 'vitest'
import { readySession, stubSession } from '../preview/testSession'
import { click, flush, mount, q, qa, setInput, typeInto } from '../ai/testUtils'
import { MatchingPage } from './MatchingPage'
import { fakeApi, json } from './opsTestKit'

const A = (id: string, status: string) => ({ id, request_ref: `R-${id}`, candidate_id: 'van-1', status, score: 900, distance_m: 120, offered_at: '2026-01-01T00:00:00Z', expires_at: '2026-01-01T00:05:00Z', decided_at: null, decided_by: null })
const RANK = { items: [{ candidate_id: 'van-1', score: 900, distance_m: 120, parts: { distance: 800, load: 50, rating: 50 } }], excluded: [{ candidate_id: 'van-2', reason: 'too_far' }] }

const api = (over: Parameters<typeof fakeApi>[0] = () => undefined) => fakeApi(over, (m, u) => {
  if (m === 'GET' && u.includes('/matching/assignments')) return json({ items: [A('1', 'offered'), A('2', 'accepted')], total: 2, limit: 100, offset: 0 })
  return json({}, 404)
})
const load = (f: typeof fetch) => mount(createElement(MatchingPage, { projectId: 'p', session: readySession(f) }))
const fill = async (cands = 'van-1, 40, -74, 1, 4000') => {
  await typeInto(q('cands') as unknown as HTMLTextAreaElement, cands)
  await setInput(q('request-ref') as HTMLInputElement, 'R-9')
  await setInput(q('request-point-lat') as HTMLInputElement, '40.01')
  await setInput(q('request-point-lng') as HTMLInputElement, '-74')
}

describe('MatchingPage', () => {
  it('gates without a session', async () => {
    const host = await mount(createElement(MatchingPage, { projectId: 'p', session: stubSession('no-origin') }))
    expect(q('matching-page-no-origin')).not.toBeNull()
    expect(host.querySelectorAll('h1')).toHaveLength(1)
  })

  it('lists assignments with their states and actions only for offered rows', async () => {
    const { f } = api()
    const host = await load(f)
    expect(host.querySelectorAll('h1')).toHaveLength(1)
    expect(qa('assignment-state').map((s) => s.textContent)).toEqual(['Offered', 'Accepted'])
    expect(qa('assignment-accept')).toHaveLength(1)
  })

  it('filters assignments by state', async () => {
    const { f, calls } = api()
    await load(f)
    await setInput(q('assignment-filter') as HTMLSelectElement, 'accepted')
    expect(calls.some((c) => c.url.includes('/matching/assignments?') && c.url.includes('status=accepted'))).toBe(true)
  })

  it('shows empty and 403 states', async () => {
    const { f } = api((_m, u) => (u.includes('/matching/assignments') ? json({ items: [], total: 0 }) : undefined))
    await load(f)
    expect(q('assignments-empty')?.textContent).toBe('No assignments yet.')
    const b = api((_m, u) => (u.includes('/matching/assignments') ? json({ code: 'forbidden', message: 'x' }, 403) : undefined))
    await load(b.f)
    expect(q('assignments-error')?.textContent).toMatch(/403/)
  })

  it('ranks candidates and posts integer micro-degrees', async () => {
    const { f, to } = api((_m, u) => (u.endsWith('/matching/rank') ? json(RANK) : undefined))
    await load(f)
    await fill('van-1, 40, -74, 1, 4000\nvan-2, 41, -74')
    await click(q('rank-run'))
    expect(to('POST', '/matching/rank')[0].body).toEqual({
      point: { lat_micro: 40_010_000, lng_micro: -74_000_000 },
      candidates: [{ id: 'van-1', lat_micro: 40_000_000, lng_micro: -74_000_000, load: 1, rating_milli: 4000 }, { id: 'van-2', lat_micro: 41_000_000, lng_micro: -74_000_000 }],
    })
    expect(qa('rank-row')[0].textContent).toContain('900')
    expect(q('rank-excluded')?.textContent).toContain('van-2 (too_far)')
  })

  it('shows input errors without calling the API', async () => {
    const { f, calls } = api()
    await load(f)
    await click(q('rank-run'))
    expect(q('solve-error')?.textContent).toMatch(/at least one candidate/)
    await fill('van-1, 99, 0')
    await click(q('rank-run'))
    expect(q('solve-error')?.textContent).toMatch(/Candidate line 1/)
    expect(calls.some((c) => c.m === 'POST')).toBe(false)
  })

  it('creates an assignment only after confirmation, once, and refreshes the list', async () => {
    const { f, to } = api((m, u) => (u.endsWith('/matching/assignments') && m === 'POST' ? json(A('9', 'offered'), 201) : undefined))
    await load(f)
    await fill()
    await click(q('assign-run'))
    expect(to('POST', '/matching/assignments')).toHaveLength(0)
    const before = to('GET', '/matching/assignments').length
    await act(async () => { q('assign-confirm-yes')!.click(); q('assign-confirm-yes')!.click() })
    await flush()
    expect(to('POST', '/matching/assignments')).toHaveLength(1)
    expect(to('POST', '/matching/assignments')[0].body).toMatchObject({ request_ref: 'R-9', point: { lat_micro: 40_010_000, lng_micro: -74_000_000 } })
    expect(q('solve-ok')?.textContent).toContain('Offered to van-1')
    expect(to('GET', '/matching/assignments').length).toBeGreaterThan(before)
  })

  it('shows a conflict from assigning (409)', async () => {
    const { f } = api((m, u) => (u.endsWith('/matching/assignments') && m === 'POST' ? json({ code: 'already_assigned', message: 'This request already has an active assignment.' }, 409) : undefined))
    await load(f)
    await fill()
    await click(q('assign-run'))
    await click(q('assign-confirm-yes'))
    expect(q('solve-error')?.textContent).toBe('This request already has an active assignment.')
  })

  it('previews a batch without confirmation and commits only after confirmation', async () => {
    const out = { pairs: [{ request_ref: 'R-1', candidate_id: 'van-1', score: 5, distance_m: 10 }], unassigned: ['R-2'], skipped: [], total_score: 5, solver: 'optimal', assignments: [] }
    const { f, to } = api((_m, u) => (u.endsWith('/matching/batch') ? json(out) : undefined))
    await load(f)
    await typeInto(q('cands') as unknown as HTMLTextAreaElement, 'van-1, 40, -74')
    await typeInto(q('batch-requests') as unknown as HTMLTextAreaElement, 'R-1, 40, -74\nR-2, 41, -74')
    await click(q('batch-run'))
    expect(to('POST', '/matching/batch')[0].body).toMatchObject({ commit: false })
    expect(q('batch-result')?.textContent).toContain('Solver: optimal')
    expect(q('batch-unassigned')?.textContent).toContain('R-2')
    await click(q('batch-commit'))
    await click(q('batch-run'))
    expect(to('POST', '/matching/batch')).toHaveLength(1)
    await click(q('batch-confirm-yes'))
    expect(to('POST', '/matching/batch')[1].body).toMatchObject({ commit: true })
  })

  it.each(['accept', 'reject', 'expire'])('%s works per row and refreshes', async (verb) => {
    const { f, to } = api((m, u) => (m === 'POST' && u.endsWith(`/matching/assignments/1/${verb}`) ? json(A('1', 'accepted')) : undefined))
    await load(f)
    const before = to('GET', '/matching/assignments').length
    await click(q(`assignment-${verb}`))
    expect(to('POST', `/assignments/1/${verb}`)).toHaveLength(1)
    expect(to('GET', '/matching/assignments').length).toBeGreaterThan(before)
  })

  it('shows a refused decision (409, 403)', async () => {
    const { f } = api((m) => (m === 'POST' ? json({ code: 'not_offered', message: 'Only an offered assignment can be decided.' }, 409) : undefined))
    await load(f)
    await click(q('assignment-accept'))
    expect(q('assignment-error')?.textContent).toBe('Only an offered assignment can be decided.')
    const g = api((m) => (m === 'POST' ? json({ code: 'forbidden', message: 'x' }, 403) : undefined))
    await load(g.f)
    await click(q('assignment-accept'))
    expect(q('assignment-error')?.textContent).toMatch(/403/)
  })

  it('expires overdue offers only after confirmation', async () => {
    const { f, to } = api((_m, u) => (u.endsWith('/matching/expire-due') ? json({ expired: 3 }) : undefined))
    await load(f)
    await click(q('expire-due'))
    expect(to('POST', '/matching/expire-due')).toHaveLength(0)
    await click(q('expire-due-confirm-yes'))
    expect(to('POST', '/matching/expire-due')).toHaveLength(1)
    expect(q('assignment-ok')?.textContent).toBe('3 overdue offer(s) expired.')
    expect(q('expire-due-confirm')).toBeNull()
  })

  it('has no axe violations', async () => {
    const out = { pairs: [{ request_ref: 'R-1', candidate_id: 'van-1', score: 5, distance_m: 10 }], unassigned: [], skipped: [], total_score: 5, solver: 'greedy', assignments: [] }
    const { f } = api((_m, u) => (u.endsWith('/matching/rank') ? json(RANK) : u.endsWith('/matching/batch') ? json(out) : undefined))
    const host = await load(f)
    await fill()
    await click(q('rank-run'))
    await typeInto(q('batch-requests') as unknown as HTMLTextAreaElement, 'R-1, 40, -74')
    await click(q('batch-run'))
    await click(q('expire-due'))
    const res = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' ')}`)).toEqual([])
  })
})
