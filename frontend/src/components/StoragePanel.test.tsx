import { createElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { byText, click, flush, mount, setInput } from '../shell/ai/testUtils'
import { StoragePanel } from './StoragePanel'

const m = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), impact: vi.fn(), sw: vi.fn() }))
vi.mock('../api/client', async (orig) => ({
  ...(await orig<typeof import('../api/client')>()),
  api: { getStorage: m.get, putStorage: m.put, storageImpact: m.impact, switchStorage: m.sw },
}))
vi.mock('./Ui', () => ({ useUi: () => ({ confirm: vi.fn(), toast: vi.fn() }) }))

const emptyRoles = { upload: [], share: [], read: [], read_all: [], delete: [], delete_all: [], operate: [] }
const cfg = (over: Record<string, unknown> = {}) => ({
  id: 's', project_id: 'p', enabled: false, backend: 's3', bucket: 'b1', region: 'eu-west-1', key_prefix: 'uploads', allowed_types: [],
  max_file_mb: 25, user_quota_mb: null, uploads_per_hour: 60, download_mode: 'proxy', allow_inline_images: false,
  roles: { ...emptyRoles, upload: ['clerk', 'ghost'] }, security: { audit_retention_days: 2555, audit_ip: true, rescan_after_days: 30, scan_timeout_seconds: 120 },
  created_at: '', updated_at: '', ...over,
})
const project = { id: 'p', name: 'P' } as never
const roles = [{ id: 'r1', name: 'clerk' }, { id: 'r2', name: 'admin' }] as never

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
  for (const f of Object.values(m)) f.mockReset()
})

const mountPanel = () => mount(createElement(StoragePanel, { project, roles, authEnabled: true, issues: null, onChanged: () => {} }))
const bucket = (host: HTMLElement) => byText(host, 'label', /Bucket name/)!.querySelector('input') as HTMLInputElement

describe('StoragePanel', () => {
  it('404 -> defaults, and saving sends the mapped payload', async () => {
    m.get.mockRejectedValue(new ApiError(404, { code: 'not_found', message: 'x', details: [] }))
    m.put.mockResolvedValue(cfg())
    const host = await mountPanel()
    await setInput(bucket(host), ' my-bucket ')
    await click(host.querySelector('input[aria-label="Upload files: clerk"]'))
    await click(byText(host, 'button', /Save file upload settings/)!)
    const body = m.put.mock.calls[0][1]
    expect(body.bucket).toBe('my-bucket')
    expect(body.roles.upload).toEqual(['clerk'])
    expect(body.max_file_mb).toBe(25)
    expect(body.user_quota_mb).toBeNull()
  })

  it('saving drops roles that no longer exist (F-1227)', async () => {
    m.get.mockResolvedValue(cfg())
    m.put.mockResolvedValue(cfg())
    const host = await mountPanel()
    await click(byText(host, 'button', /Save file upload settings/)!)
    expect(m.put.mock.calls[0][1].roles.upload).toEqual(['clerk'])
  })

  it('switching on keeps unsaved edits (F-1228)', async () => {
    m.get.mockResolvedValue(cfg())
    m.impact.mockResolvedValue({ action: 'enable', enabled: false, can_proceed: true, blockers: [], warnings: [] })
    m.sw.mockResolvedValue(cfg({ enabled: true }))
    const host = await mountPanel()
    await setInput(bucket(host), 'edited-bucket')
    await click(byText(host, 'button', /Turn on…/)!)
    await flush()
    await click(byText(host, 'dialog button', /Turn on file uploads/)!)
    await flush()
    expect(m.sw).toHaveBeenCalledWith('p', 'enable')
    expect(bucket(host).value).toBe('edited-bucket')
    expect(host.textContent).toContain('File uploads are on for this project')
  })

  it('blockers disable the confirm button', async () => {
    m.get.mockResolvedValue(cfg())
    m.impact.mockResolvedValue({ action: 'enable', enabled: false, can_proceed: false, blockers: ['no scanner'], warnings: [] })
    const host = await mountPanel()
    await click(byText(host, 'button', /Turn on…/)!)
    await flush()
    expect(host.textContent).toContain('no scanner')
    expect((byText(host, 'dialog button', /Turn on file uploads/)! as HTMLButtonElement).disabled).toBe(true)
  })
})
