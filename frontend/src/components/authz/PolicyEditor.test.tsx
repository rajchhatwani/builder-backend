import { act, createElement } from 'react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { byText, click, flush, mount } from '../../shell/ai/testUtils'
import { PolicyEditor } from './PolicyEditor'
import type { AuthorizationSettings } from '../../api/types'
import type { Catalogue } from './policyModel'

vi.mock('../Ui', () => ({ useUi: () => ({ confirm: vi.fn(), toast: vi.fn() }) }))

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
})

const catalogue: Catalogue = { resource: { Post: {} }, subject: { id: 'uuid' }, roles: [], entities: [{ name: 'Post', ops: ['list'] }] }
const settings = {
  project_id: 'p', model: 'abac', attachments: {}, field_access: [], version: 1, updated_at: null,
  policies: [{ id: 'own', description: '', effect: 'allow', actions: ['Post.list'], when: null }],
} as unknown as AuthorizationSettings

describe('PolicyEditor (F-0570)', () => {
  it('shows the server error inside the modal', async () => {
    const onSave = vi.fn().mockResolvedValue('unknown_resource_attribute: foo')
    const host = await mount(createElement(PolicyEditor, { settings, catalogue, onSave }))
    await click(byText(host, 'button', /^Edit$/) ?? null)
    await act(async () => { host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })
    await flush()
    const dialog = host.querySelector('dialog')!
    expect(onSave).toHaveBeenCalled()
    expect(dialog.textContent).toContain('unknown_resource_attribute: foo')
    expect(dialog.textContent).not.toContain('See the message above')
  })
})
