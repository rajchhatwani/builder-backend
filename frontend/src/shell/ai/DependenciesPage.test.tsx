import { createElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DependenciesPage } from './DependenciesPage'
import { click, mount, q, qa, setInput } from './testUtils'

const m = vi.hoisted(() => ({ policy: vi.fn(), reqs: vi.fn(), blocks: vi.fn(), hooks: vi.fn(), deps: vi.fn(), request: vi.fn(), approve: vi.fn(), deny: vi.fn(), revoke: vi.fn(), approveHook: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({
  ...(await orig<typeof import('../../api/client')>()),
  api: { dependencyPolicy: m.policy, listDependencyRequests: m.reqs, registryBlocks: m.blocks, registryHooks: m.hooks, registryDeps: m.deps, requestDependency: m.request, approveDependency: m.approve, denyDependency: m.deny, revokeDependency: m.revoke, approveRegistryHook: m.approveHook },
}))

const req = (id: string, status: string) => ({ id, package: 'httpx', version: '0.27.0', reason: 'calls', hashes: ['sha256:aa'], status, requested_by: null, decided_by: null, decided_at: null, decision_note: null, expires_at: null, revoked_by: null, revoked_at: null, created_at: '' })
const HOOK = { id: 'h1', hook_name: 'on_create', content_hash: 'a'.repeat(64), author: 'ann', approved_by: null, created_at: '' }
beforeEach(() => {
  Object.values(m).forEach((f) => f.mockReset())
  m.policy.mockResolvedValue({ curated_sets: {}, allow_list: ['requests'], approved: [], pending_requests: 1 })
  m.reqs.mockResolvedValue([req('r1', 'pending'), req('r2', 'approved')])
  m.blocks.mockResolvedValue([]); m.hooks.mockResolvedValue([HOOK]); m.deps.mockResolvedValue([])
})

describe('DependenciesPage', () => {
  it('shows policy, requests and registry', async () => {
    await mount(createElement(DependenciesPage, { projectId: 'p' }))
    expect(q('deps-pending-count')?.textContent).toContain('1 request is waiting')
    expect(qa('deps-row').map((r) => r.getAttribute('data-status'))).toEqual(['pending', 'approved'])
    expect(q('registry-hook')).not.toBeNull()
  })

  it('approves only after confirm and echoes the reviewed request', async () => {
    m.approve.mockResolvedValue(req('r1', 'approved'))
    await mount(createElement(DependenciesPage, { projectId: 'p' }))
    await click(q('deps-approve'))
    expect(m.approve).not.toHaveBeenCalled()
    await setInput(q('deps-note') as HTMLInputElement, 'ok')
    await click(q('deps-confirm-confirm'))
    expect(m.approve).toHaveBeenCalledWith('p', expect.objectContaining({ id: 'r1', package: 'httpx', hashes: ['sha256:aa'] }), 'ok')
    expect(q('deps-confirm')).toBeNull()
  })

  it('denies and revokes through the same confirm step', async () => {
    m.deny.mockResolvedValue(req('r1', 'denied')); m.revoke.mockResolvedValue(req('r2', 'revoked'))
    await mount(createElement(DependenciesPage, { projectId: 'p' }))
    await click(q('deps-deny')); await click(q('deps-confirm-confirm'))
    expect(m.deny).toHaveBeenCalledWith('p', 'r1', '')
    await click(q('deps-revoke')); await click(q('deps-confirm-confirm'))
    expect(m.revoke).toHaveBeenCalledWith('p', 'r2', '')
  })

  it('sends a request, approves a hook, and shows a refusal', async () => {
    m.request.mockResolvedValue(req('r3', 'pending')); m.approveHook.mockResolvedValue({ ...HOOK, approved_by: 'u' })
    await mount(createElement(DependenciesPage, { projectId: 'p' }))
    expect((q('deps-request') as HTMLButtonElement).disabled).toBe(true)
    await setInput(q('deps-package') as HTMLInputElement, 'httpx'); await setInput(q('deps-version') as HTMLInputElement, '0.27.0'); await setInput(q('deps-reason') as HTMLInputElement, 'for calls')
    await click(q('deps-request'))
    expect(m.request).toHaveBeenCalledWith('p', { package: 'httpx', version: '0.27.0', reason: 'for calls' })
    await click(q('registry-hook-approve'))
    expect(m.approveHook).toHaveBeenCalledWith('p', 'h1')
    m.deny.mockRejectedValueOnce(new Error('only an owner can decide'))
    await click(q('deps-deny')); await click(q('deps-confirm-confirm'))
    expect(q('deps-error')?.textContent).toContain('only an owner')
  })
})
