import { createElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { click, flush, mount } from '../shell/ai/testUtils'
import { ApiError } from '../api/client'
import { PermissionsPanel } from './PermissionsPanel'

const m = vi.hoisted(() => ({ list: vi.fn(), bulk: vi.fn(), del: vi.fn(), confirm: vi.fn() }))
vi.mock('../api/client', async (orig) => ({
  ...(await orig<typeof import('../api/client')>()),
  api: { listAllPermissions: m.list, bulkUpsertPermissions: m.bulk, deletePermission: m.del },
}))
vi.mock('./Ui', () => ({ useUi: () => ({ confirm: m.confirm, toast: vi.fn() }) }))

const entities = [{ id: 'e1', name: 'Post' }] as never
const roles = [{ id: 'r1', name: 'admin', label: 'admin' }] as never
const perm = (id: string, op: string, rolesList: string[]) => ({
  id, entity_id: 'e1', operation: op, roles: rolesList, row_rule: null,
  custom_filter_field: null, custom_filter_value: null,
})

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
  m.confirm.mockReset(); m.confirm.mockResolvedValue(true)
  m.list.mockReset(); m.bulk.mockReset(); m.del.mockReset()
  m.del.mockResolvedValue(undefined)
})

async function clearCellAndSave(host: HTMLElement, op: string) {
  const cell = host.querySelector(`td[title="Click to edit permissions for Post:${op}"]`) as HTMLElement
  await click(cell)
  const box = host.querySelector('dialog input[type="checkbox"]') as HTMLInputElement
  await click(box) // untick the only role
  await click(host.querySelector('dialog button[type="submit"]'))
  const save = Array.from(host.querySelectorAll('button')).find((b) => /Save all/.test(b.textContent ?? ''))
  await click(save!)
  await flush()
}

describe('PermissionsPanel revoke', () => {
  it('deletes a slot that was cleared instead of silently dropping it', async () => {
    m.list.mockResolvedValue([perm('p-list', 'list', ['admin']), perm('p-get', 'get', ['admin'])])
    m.bulk.mockResolvedValue([perm('p-get', 'get', ['admin'])])
    const host = await mount(createElement(PermissionsPanel, { projectId: 'p', entities, roles }))
    await clearCellAndSave(host, 'list')
    expect(m.del).toHaveBeenCalledWith('p-list', false)
    expect(host.textContent).not.toContain('No permissions configured')
  })

  it('can revoke the only configured permission', async () => {
    m.list.mockResolvedValue([perm('p-list', 'list', ['admin'])])
    const host = await mount(createElement(PermissionsPanel, { projectId: 'p', entities, roles }))
    await clearCellAndSave(host, 'list')
    expect(m.del).toHaveBeenCalledWith('p-list', false)
    expect(m.bulk).not.toHaveBeenCalled()
    expect(host.textContent).not.toContain('No permissions configured')
  })

  it('asks and retries a cleared slot with confirm when the server answers access_weakened (F-0902)', async () => {
    m.list.mockResolvedValue([perm('p-list', 'list', ['admin'])])
    m.del.mockRejectedValueOnce(new ApiError(409, { code: 'access_weakened', message: 'more access', details: [] }))
    const host = await mount(createElement(PermissionsPanel, { projectId: 'p', entities, roles }))
    await clearCellAndSave(host, 'list')
    expect(m.del.mock.calls).toEqual([['p-list', false], ['p-list', true]])
  })

  it('reloads the matrix when the delete confirm is declined after a bulk upsert persisted (F-0905)', async () => {
    m.list.mockResolvedValueOnce([perm('p-list', 'list', ['admin']), perm('p-get', 'get', ['admin'])])
    m.bulk.mockResolvedValue([perm('p-get', 'get', ['admin'])])
    m.del.mockRejectedValueOnce(new ApiError(409, { code: 'access_weakened', message: 'more access', details: [] }))
    m.confirm.mockResolvedValue(false)
    m.list.mockResolvedValue([perm('p-get', 'get', ['admin'])])
    const host = await mount(createElement(PermissionsPanel, { projectId: 'p', entities, roles }))
    await clearCellAndSave(host, 'list')
    expect(m.bulk).toHaveBeenCalled()
    expect(m.list).toHaveBeenCalledTimes(2)
  })

  it('reloads the matrix when a later delete fails after an earlier one persisted (F-1205)', async () => {
    m.list.mockResolvedValueOnce([perm('p-list', 'list', ['admin']), perm('p-get', 'get', ['admin'])])
    m.del.mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error('boom'))
    m.list.mockResolvedValue([perm('p-get', 'get', ['admin'])])
    const host = await mount(createElement(PermissionsPanel, { projectId: 'p', entities, roles }))
    for (const op of ['list', 'get']) {
      await click(host.querySelector(`td[title="Click to edit permissions for Post:${op}"]`) as HTMLElement)
      await click(host.querySelector('dialog input[type="checkbox"]') as HTMLInputElement)
      await click(host.querySelector('dialog button[type="submit"]'))
    }
    const save = Array.from(host.querySelectorAll('button')).find((b) => /Save all/.test(b.textContent ?? ''))
    await click(save!)
    await flush()
    expect(m.del).toHaveBeenCalledTimes(2)
    expect(m.list).toHaveBeenCalledTimes(2)
  })
})
