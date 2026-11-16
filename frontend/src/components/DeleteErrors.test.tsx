import { createElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { click, mount } from '../shell/ai/testUtils'
import { AuthCustomFieldsPanel } from './AuthCustomFieldsPanel'
import { DataModelPanel } from './DataModelPanel'

const m = vi.hoisted(() => ({
  toast: vi.fn(), delField: vi.fn(), listFields: vi.fn(), delEntity: vi.fn(),
}))
vi.mock('../api/client', async (orig) => ({
  ...(await orig<typeof import('../api/client')>()),
  api: {
    listAuthCustomFields: m.listFields, deleteAuthCustomField: m.delField,
    listAllFields: m.listFields, listFields: m.listFields, deleteEntity: m.delEntity,
  },
}))
vi.mock('./Ui', () => ({ useUi: () => ({ confirm: vi.fn(async () => true), toast: m.toast }) }))

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
  Object.values(m).forEach((f) => f.mockReset())
})

describe('delete failures are shown, not thrown', () => {
  it('auth custom field delete', async () => {
    const field = { id: 'f1', name: 'phone', label: 'Phone', type: 'string', required: false, unique: false, indexed: false, enum_values: null }
    m.listFields.mockResolvedValue({ items: [field], total: 1 })
    m.delField.mockRejectedValue(new Error('forbidden'))
    const host = await mount(createElement(AuthCustomFieldsPanel, { projectId: 'p' }))
    const del = Array.from(host.querySelectorAll('button')).find((b) => /delete/i.test(b.textContent ?? ''))
    await click(del!)
    expect(m.delField).toHaveBeenCalled()
    expect(m.toast).toHaveBeenCalledWith('forbidden', 'danger')
  })

  it('entity delete', async () => {
    m.listFields.mockResolvedValue({ items: [], total: 0 })
    m.delEntity.mockRejectedValue(new Error('in use'))
    const entity = { id: 'e1', name: 'Post', table_name: 'posts', plural_path: 'posts', options: { operations: [], filterable: [], sortable: [], searchable: [], default_page_size: 20, max_page_size: 100, soft_delete: false } } as never
    const host = await mount(createElement(DataModelPanel, { projectId: 'p', entities: [entity], relations: [], loading: false, onChanged: vi.fn() }))
    const del = Array.from(host.querySelectorAll('button')).find((b) => /delete/i.test(b.textContent ?? ''))
    await click(del!)
    expect(m.toast).toHaveBeenCalledWith('in use', 'danger')
  })
})
