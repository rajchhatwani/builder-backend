import axe from 'axe-core'
import { createElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { click, flush, mount, qa, q, unmount } from '../ai/testUtils'
import { ApiError } from '../../api/client'

const m = vi.hoisted(() => ({ score: vi.fn(), list: vi.fn(), create: vi.fn(), get: vi.fn(), patch: vi.fn(), dismiss: vi.fn(), applied: vi.fn(), save: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({
  ...(await orig<typeof import('../../api/client')>()),
  saveBlob: m.save,
  api: { getScorecard: m.score, listUpgrades: m.list, createUpgrade: m.create, getUpgrade: m.get, getUpgradePatch: m.patch, dismissUpgrade: m.dismiss, markUpgradeApplied: m.applied },
}))
import { UpgradesPage } from './UpgradesPage'

const ID = '11111111-2222-3333-4444-555555555555'
const chk = (id: string, group: string, status: string, action = 'none') => ({ id, group, status, detail: `detail of ${id}`, fix: { action, route: '' } })
const card = { score: 72, passing: false, checks: [chk('s1', 'security', 'pass'), chk('s2', 'security', 'fail', 'regenerate'), chk('d1', 'dependency_freshness', 'warn', 'open_upgrade'), chk('h1', 'hook_coverage', 'warn', 'redeclare_hook'), chk('b1', 'block_version_lag', 'warn'), chk('dr1', 'drift', 'fail', 'open_upgrade')] }
const summary = (o: Record<string, unknown> = {}) => ({ id: ID, project_id: 'p', base_generation_id: 'g', status: 'open', from_generator_version: '1.0.0', to_generator_version: '1.1.0', block_changes: [], file_count: 2, auto_apply_eligible: false, created_at: '2026-11-01T10:00:00Z', decided_at: null, ...o })
const detail = (o: Record<string, unknown> = {}) => ({
  ...summary(), created_by: null, patch_size: 40, kept: ['app/custom/x.py'],
  block_changes: [{ block: 'auth', from: '1.0.0', to: '1.0.1', bump: 'patch' }],
  files: [{ path: 'app/main.py', zone: 'generated', change: 'modified' }, { path: 'app/new.py', zone: 'owner', change: 'added' }],
  sbom_diff: { added: [{ name: 'httpx', spec: '>=0.27' }], removed: [], changed: [{ name: 'fastapi', from: '0.110', to: '0.115' }] },
  migrations: [{ path: 'alembic/versions/a.py', change: 'added' }], scorecard: { passing: true }, ...o,
})
const PATCH = 'diff --git a/app/main.py b/app/main.py\n+hello'
const apiErr = (status: number, code: string) => new ApiError(status, { code, message: `server ${code}`, details: [] })
const page = (pid = 'p') => createElement(UpgradesPage, { projectId: pid })

beforeEach(() => {
  Object.values(m).forEach((f) => f.mockReset())
  m.score.mockResolvedValue(card); m.list.mockResolvedValue({ items: [summary()], total: 1, limit: 50, offset: 0 })
  m.get.mockResolvedValue(detail()); m.patch.mockResolvedValue(PATCH)
})
afterEach(() => { vi.restoreAllMocks() })

describe('UpgradesPage', () => {
  it('renders the scorecard grouped, with detail and fix actions on non-pass checks only', async () => {
    const h = await mount(page())
    expect(q('score')?.textContent).toContain('72')
    expect(q('passing')?.textContent).toContain('Not passing')
    expect(qa('check-group').map((g) => g.dataset.group)).toEqual(['security', 'dependency_freshness', 'hook_coverage', 'block_version_lag', 'drift'])
    expect(qa('check-detail')).toHaveLength(5) // the passing check shows none
    expect(h.querySelector('[data-testid="fix-regenerate"]')?.getAttribute('href')).toBe('#/p/p/generate')
    expect(h.querySelector('[data-testid="fix-hook"]')?.getAttribute('href')).toBe('#/p/p/hooks')
    expect(qa('fix-none')).toHaveLength(1)
    expect(qa('fix-open-upgrade')).toHaveLength(2)
  })

  it('open_upgrade fix creates a proposal and opens it', async () => {
    m.create.mockResolvedValue(detail())
    await mount(page())
    await click(qa('fix-open-upgrade')[0])
    expect(m.create).toHaveBeenCalledWith('p')
    expect(m.list).toHaveBeenCalledTimes(2)
    expect(q('detail')).not.toBeNull()
  })

  it('create button creates a proposal', async () => {
    m.create.mockResolvedValue(detail())
    await mount(page())
    await click(q('create-proposal'))
    expect(m.create).toHaveBeenCalledTimes(1)
  })

  it.each([
    ['no_baseline', /Generate and download the project once/],
    ['up_to_date', /nothing to upgrade/],
    ['proposal_open', /already open/],
    ['proposal_closed', /already closed/],
    ['baseline_unavailable', /before upgrades existed/],
  ])('maps 409 %s to a plain message', async (code, re) => {
    m.create.mockRejectedValue(apiErr(409, code))
    await mount(page())
    await click(q('create-proposal'))
    expect(q('create-error')?.textContent).toMatch(re)
    expect(q('create-error')?.textContent).not.toContain('server ')
    expect((q('create-proposal') as HTMLButtonElement).disabled).toBe(false)
  })

  it('lists proposals with status', async () => {
    await mount(page())
    expect(qa('proposal')).toHaveLength(1)
    expect(q('proposal-status')?.textContent).toBe('open')
  })

  it('detail shows block bump, files, sbom, migrations, eligibility, patch and downloads it', async () => {
    const h = await mount(page())
    await click(h.querySelector('[data-testid="proposal"] button'))
    expect(q('bump')?.textContent).toBe('patch')
    expect(qa('file-row')).toHaveLength(2)
    expect(q('sbom')?.textContent).toContain('httpx')
    expect(q('sbom')?.textContent).toContain('0.110 to 0.115')
    expect(q('migrations')?.textContent).toContain('alembic/versions/a.py')
    expect(q('eligibility')?.textContent).toContain('Not eligible: the proposal adds or changes a database migration')
    expect(q('patch')?.textContent).toBe(PATCH)
    expect(q('apply-command')?.textContent).toBe('git apply --3way upgrade-11111111.patch')
    await click(q('download-patch'))
    expect(m.save).toHaveBeenCalledTimes(1)
    expect(m.save.mock.calls[0][1]).toBe('upgrade-11111111.patch')
  })

  it('shows an eligible reason when the server flags it', async () => {
    m.get.mockResolvedValue(detail({ auto_apply_eligible: true, migrations: [] }))
    const h = await mount(page())
    await click(h.querySelector('[data-testid="proposal"] button'))
    expect(q('eligibility')?.textContent).toContain('Eligible: every block change is a patch bump')
  })

  it('dismiss and mark applied exist only for open proposals and need a confirm', async () => {
    const h = await mount(page())
    await click(h.querySelector('[data-testid="proposal"] button'))
    expect(q('dismiss')).not.toBeNull(); expect(q('mark-applied')).not.toBeNull()
    m.dismiss.mockResolvedValue(detail({ status: 'dismissed', decided_at: '2026-11-02T00:00:00Z' }))
    await click(q('dismiss'))
    expect(m.dismiss).not.toHaveBeenCalled()
    await click(q('confirm-decide'))
    expect(m.dismiss).toHaveBeenCalledWith('p', ID)
    expect(q('dismiss')).toBeNull(); expect(q('mark-applied')).toBeNull()
    expect(q('closed-note')?.textContent).toContain('dismissed')
  })

  it('mark applied calls the applied route; a 409 proposal_closed is explained', async () => {
    m.applied.mockRejectedValue(apiErr(409, 'proposal_closed'))
    const h = await mount(page())
    await click(h.querySelector('[data-testid="proposal"] button'))
    await click(q('mark-applied')); await click(q('confirm-decide'))
    expect(m.applied).toHaveBeenCalledWith('p', ID)
    expect(q('decide-error')?.textContent).toMatch(/already closed/)
  })

  it.each(['applied', 'dismissed'])('a %s proposal has no decision buttons', async (status) => {
    m.get.mockResolvedValue(detail({ status }))
    const h = await mount(page())
    await click(h.querySelector('[data-testid="proposal"] button'))
    expect(q('detail')).not.toBeNull()
    expect(q('dismiss')).toBeNull(); expect(q('mark-applied')).toBeNull()
  })

  it('failed loads end in an error with retry, never a stuck spinner', async () => {
    m.score.mockRejectedValue(new Error('nope')); m.list.mockRejectedValue(apiErr(500, 'boom'))
    const h = await mount(page())
    expect(q('scorecard-error')?.textContent).toContain('nope')
    expect(q('list-error')?.textContent).toContain('server boom')
    expect(h.textContent).not.toContain('Loading')
    m.score.mockResolvedValue(card)
    await click(q('scorecard-error')?.querySelector('button') ?? null)
    expect(q('scorecard')).not.toBeNull()
  })

  it('a patch load failure does not hide the rest of the proposal', async () => {
    m.patch.mockRejectedValue(apiErr(500, 'x'))
    const h = await mount(page())
    await click(h.querySelector('[data-testid="proposal"] button'))
    expect(q('patch-error')).not.toBeNull(); expect(q('files')).not.toBeNull()
  })

  it('has one h1, no skipped level, and no axe violations (with detail open)', async () => {
    const h = await mount(page())
    await click(h.querySelector('[data-testid="proposal"] button'))
    expect(h.querySelectorAll('h1')).toHaveLength(1)
    const levels = Array.from(h.querySelectorAll('h1,h2,h3,h4')).map((e) => Number(e.tagName[1]))
    levels.forEach((l, i) => { if (i) expect(l - levels[i - 1]).toBeLessThanOrEqual(1) })
    const r = await axe.run(h, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } })
    expect(r.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' | ')}`)).toEqual([])
  })

  it('project change resets the page and a late answer from the old project is dropped', async () => {
    let late: (v: unknown) => void = () => {}
    m.score.mockImplementationOnce(() => new Promise((r) => { late = r }))
    const { createRoot } = await import('react-dom/client')
    const { act } = await import('react')
    const host = document.createElement('div'); document.body.appendChild(host)
    const root = createRoot(host)
    await act(async () => { root.render(page('a')) }); await flush()
    m.score.mockResolvedValueOnce({ ...card, score: 11, checks: [] })
    await act(async () => { root.render(page('b')) }); await flush()
    await act(async () => { late({ ...card, score: 99 }) }); await flush()
    expect(host.querySelector('[data-testid="score"]')?.textContent).toContain('11')
    expect(m.score).toHaveBeenLastCalledWith('b')
    act(() => root.unmount()); host.remove(); unmount()
  })

  it('project change closes an open detail', async () => {
    const { createRoot } = await import('react-dom/client')
    const { act } = await import('react')
    const host = document.createElement('div'); document.body.appendChild(host)
    const root = createRoot(host)
    await act(async () => { root.render(page('a')) }); await flush()
    await act(async () => { (host.querySelector('[data-testid="proposal"] button') as HTMLElement).click() }); await flush()
    expect(host.querySelector('[data-testid="detail"]')).not.toBeNull()
    await act(async () => { root.render(page('b')) }); await flush()
    expect(host.querySelector('[data-testid="detail"]')).toBeNull()
    act(() => root.unmount()); host.remove()
  })
})
