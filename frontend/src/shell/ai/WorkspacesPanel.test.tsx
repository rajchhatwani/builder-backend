import { createElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { WorkspacesPanel } from './WorkspacesPanel'
import { click, flush, mount, q, qa, setInput } from './testUtils'

const m = vi.hoisted(() => ({ list: vi.fn(), create: vi.fn(), checkpoint: vi.fn(), rollback: vi.fn(), discard: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({
  ...(await orig<typeof import('../../api/client')>()),
  api: { listWorkspaces: m.list, createWorkspace: m.create, createCheckpoint: m.checkpoint, rollbackWorkspace: m.rollback, discardWorkspace: m.discard },
}))

const CP = { id: 'c1', workspace_id: 'w1', label: 'before refactor', git_sha: 'abc', spec_seq: 3, spec_hash: 'h', has_data_snapshot: false, created_at: '2026-01-02T03:04:05Z' }
const WS = { id: 'w1', project_id: 'p', name: 'draft', state: 'active', base_spec_seq: 1, spec_seq: 3, branch: 'ws/w1', created_at: '', updated_at: '', checkpoints: [CP] }
beforeEach(() => { Object.values(m).forEach((f) => f.mockReset()); m.list.mockResolvedValue([WS]) })

describe('WorkspacesPanel', () => {
  it('lists workspaces with their checkpoints and shows the empty state', async () => {
    await mount(createElement(WorkspacesPanel, { projectId: 'p' }))
    expect(qa('ws-item')).toHaveLength(1)
    expect(qa('ws-checkpoint-item')[0].textContent).toContain('before refactor')
    m.list.mockResolvedValue([])
    await mount(createElement(WorkspacesPanel, { projectId: 'p' }))
    expect(q('ws-empty')).not.toBeNull()
  })

  it('creates a workspace and saves a checkpoint with the typed label', async () => {
    m.create.mockResolvedValue(WS); m.checkpoint.mockResolvedValue(CP)
    await mount(createElement(WorkspacesPanel, { projectId: 'p' }))
    await setInput(q('ws-name') as HTMLInputElement, ' try it ')
    await click(q('ws-create'))
    expect(m.create).toHaveBeenCalledWith('p', 'try it')
    await setInput(q('ws-label') as HTMLInputElement, 'v1')
    await click(q('ws-checkpoint'))
    expect(m.checkpoint).toHaveBeenCalledWith('p', 'w1', 'v1')
  })

  it('rolls back only after the confirm step, and Cancel does nothing', async () => {
    m.rollback.mockResolvedValue(WS)
    await mount(createElement(WorkspacesPanel, { projectId: 'p' }))
    await click(q('ws-rollback'))
    expect(q('ws-confirm')?.getAttribute('role')).toBe('alertdialog')
    expect(m.rollback).not.toHaveBeenCalled()
    await click(q('ws-confirm-cancel'))
    expect(q('ws-confirm')).toBeNull()
    await click(q('ws-rollback'))
    await click(q('ws-confirm-confirm'))
    expect(m.rollback).toHaveBeenCalledWith('p', 'w1', 'c1')
    expect(q('ws-confirm')).toBeNull()
  })

  it('discards after confirmation and keeps the prompt open with the error when it fails', async () => {
    m.discard.mockRejectedValueOnce(new ApiError(409, { code: 'conflict', message: 'a run is using it', details: [] }))
    await mount(createElement(WorkspacesPanel, { projectId: 'p' }))
    await click(q('ws-discard'))
    await click(q('ws-confirm-confirm'))
    await flush()
    expect(m.discard).toHaveBeenCalledWith('p', 'w1')
    expect(q('ws-error')?.textContent).toContain('a run is using it')
    expect(q('ws-confirm')).not.toBeNull()
  })
})
