import axe from 'axe-core'
import { createElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api } from '../../api/client'
import * as client from '../../api/client'
import { click, flush, mount, q, qa, setInput } from '../ai/testUtils'
import { CompliancePage } from './CompliancePage'

const role = vi.hoisted(() => ({ value: 'editor' as string | null }))
vi.mock('../ai/useMyRole', () => ({ useMyRole: () => role.value }))
vi.mock('../../api/client', async (orig) => ({ ...(await orig<typeof import('../../api/client')>()), saveBlob: vi.fn() }))

const ctl = (o: Record<string, unknown>) => ({ id: 'CC6.1', framework: 'soc2', title: 'Logical access', description: 'Access is restricted', status: 'met', reason: 'Roles are defined', evidence: [{ label: 'Roles block', path: 'authorization' }], tests: [{ file: 'tests/test_authz.py', name: 'test_roles' }], ...o })
const REPORT = {
  framework: null, met: 1, unmet: 1, not_applicable: 1,
  controls: [
    ctl({}),
    ctl({ id: 'CC7.2', title: 'Retention', status: 'unmet', reason: 'Switch on retention rules', evidence: [], tests: [] }),
    ctl({ id: 'PCI-3', framework: 'pci', title: 'Card data', status: 'not_applicable', reason: 'No payments', evidence: [], tests: [] }),
  ],
}
const COMPLIANCE = { enabled: true, roles: ['admin'], retention: [{ entity: 'order', days: 30, date_field: 'created_at', action: 'purge', anonymise_fields: [] }], consent_purposes: ['marketing'], break_glass: { enabled: false, roles: [], max_minutes: 60 }, export_entities: [], export_fields: [], export_consent_purpose: null, extra_key: 1 }

let controls: ReturnType<typeof vi.spyOn>
let getBlock: ReturnType<typeof vi.spyOn>
let putBlock: ReturnType<typeof vi.spyOn>
let issues: ReturnType<typeof vi.spyOn>
let dl: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  role.value = 'editor'
  controls = vi.spyOn(api, 'getComplianceControls').mockResolvedValue(REPORT)
  getBlock = vi.spyOn(api, 'getBlock').mockImplementation(async (_p: string, name: string) => (name === 'compliance' ? { compliance: COMPLIANCE, version: 3 } : { regulated: { enabled: true, key_provider: 'file', fields: [{ entity: 'patient', field: 'ssn' }, { entity: 'patient', field: 'dob' }] }, version: 1 }))
  putBlock = vi.spyOn(api, 'putBlock').mockImplementation(async (_p: string, _n: string, body: Record<string, unknown>) => ({ compliance: body.compliance, version: 4 }))
  issues = vi.spyOn(api, 'getBehaviorIssues').mockResolvedValue({ issues: [] })
  dl = vi.spyOn(api, 'downloadComplianceEvidence').mockResolvedValue({ blob: new Blob(['zip']), filename: 'evidence.zip' })
  vi.mocked(client.saveBlob).mockClear()
})
afterEach(() => { vi.restoreAllMocks() })

const el = () => createElement(CompliancePage, { projectId: 'p' })
const input = (id: string) => document.getElementById(id) as HTMLInputElement
const typeKeys = async (id: string, text: string) => { for (let i = 1; i <= text.length; i++) await setInput(input(id), text.slice(0, i)) }

describe('Compliance page: controls', () => {
  it('has one h1 and no skipped heading level', async () => {
    const host = await mount(el())
    expect(host.querySelectorAll('h1')).toHaveLength(1)
    const levels = Array.from(host.querySelectorAll('h1,h2,h3,h4')).map((h) => Number(h.tagName[1]))
    levels.forEach((l, i) => { if (i) expect(l - levels[i - 1]).toBeLessThanOrEqual(1) })
  })

  it('shows counts, status as text, evidence and tests, and filters by status', async () => {
    await mount(el())
    expect(q('controls-summary')?.textContent).toBe('1 met, 1 unmet, 1 not applicable.')
    expect(qa('control-row')).toHaveLength(3)
    expect(qa('control-status').map((c) => c.textContent)).toEqual(['✓ Met', '✗ Unmet', '– Not applicable'])
    expect(qa('control-row')[0].textContent).toContain('Roles block (path: authorization)')
    expect(qa('control-row')[0].textContent).toContain('tests/test_authz.py::test_roles')
    await setInput(document.getElementById('controls-filter') as unknown as HTMLSelectElement, 'unmet')
    expect(qa('control-row').map((r) => r.dataset.status)).toEqual(['unmet'])
    expect(q('goto-settings')).not.toBeNull()
  })

  it('an unmet control moves focus to the settings section', async () => {
    await mount(el())
    await click(q('goto-settings'))
    expect(document.activeElement?.id).toBe('compliance-settings')
  })

  it('framework buttons request that framework', async () => {
    await mount(el())
    expect(controls).toHaveBeenLastCalledWith('p', undefined)
    await click(q('fw-hipaa'))
    expect(controls).toHaveBeenLastCalledWith('p', 'hipaa')
    expect(q('fw-hipaa')?.getAttribute('aria-pressed')).toBe('true')
  })

  it('ignores a stale framework answer that arrives late', async () => {
    let first!: (v: unknown) => void
    controls.mockImplementationOnce(() => new Promise((r) => { first = r }))
    await mount(el())
    controls.mockResolvedValueOnce({ ...REPORT, met: 9, controls: [] })
    await click(q('fw-pci'))
    first({ ...REPORT, met: 5 })
    await flush()
    expect(q('controls-summary')?.textContent).toContain('9 met')
  })

  it('surfaces a load error and a 200 that is not a controls report', async () => {
    controls.mockRejectedValueOnce(new ApiError(500, { code: 'x', message: 'boom', details: [] }))
    await mount(el())
    expect(q('controls-error')?.textContent).toContain('boom')
    controls.mockResolvedValueOnce('<html>proxy</html>')
    await click(q('controls-error')!.querySelector('button'))
    expect(q('controls-error')?.textContent).toContain('not a controls report')
  })

  it('download calls the client with the framework and saves the blob', async () => {
    await mount(el())
    expect((q('evidence-download') as HTMLButtonElement).disabled).toBe(true)
    expect(q('evidence-hint')).not.toBeNull()
    await click(q('fw-soc2'))
    await click(q('evidence-download'))
    expect(dl).toHaveBeenCalledWith('p', 'soc2')
    expect(client.saveBlob).toHaveBeenCalledTimes(1)
    expect(vi.mocked(client.saveBlob).mock.calls[0][1]).toBe('evidence.zip')
    expect(q('evidence-note')?.textContent).toContain('evidence.zip')
  })

  it('download shows busy state and surfaces an error', async () => {
    let fail!: (e: Error) => void
    dl.mockImplementationOnce(() => new Promise((_, rej) => { fail = rej }))
    await mount(el())
    await click(q('fw-pci'))
    await click(q('evidence-download'))
    expect((q('evidence-download') as HTMLButtonElement).disabled).toBe(true)
    fail(new Error('no evidence yet'))
    await flush()
    expect(q('evidence-error')?.textContent).toBe('no evidence yet')
    expect(client.saveBlob).not.toHaveBeenCalled()
    expect((q('evidence-download') as HTMLButtonElement).disabled).toBe(false)
  })
})

describe('Compliance page: settings', () => {
  it('saves the exact payload (unmanaged keys kept, version sent) and refreshes the controls', async () => {
    await mount(el())
    await setInput(input('cmp-purposes'), 'marketing, research')
    await click(q('add-export-field'))
    const row = q('export-field-row')!
    await setInput(row.querySelector('input[id$="-entity"]') as HTMLInputElement, 'patient')
    await setInput(row.querySelector('input[id$="-field"]') as HTMLInputElement, 'zip')
    await setInput(row.querySelector('select') as unknown as HTMLInputElement, 'generalise')
    const calls = controls.mock.calls.length
    await click(q('settings-save'))
    expect(putBlock).toHaveBeenCalledTimes(1)
    expect(putBlock.mock.calls[0]).toEqual(['p', 'compliance', {
      compliance: {
        extra_key: 1, enabled: true, roles: ['admin'],
        retention: [{ entity: 'order', days: 30, date_field: 'created_at', action: 'purge', anonymise_fields: [] }],
        consent_purposes: ['marketing', 'research'],
        break_glass: { enabled: false, roles: [], max_minutes: 60 },
        export_entities: [], export_fields: [{ entity: 'patient', field: 'zip', treatment: 'generalise' }], export_consent_purpose: null,
      },
      expected_version: 3,
    }])
    expect(q('settings-note')?.textContent).toBe('Saved (version 4).')
    expect(controls.mock.calls.length).toBeGreaterThan(calls)
  })

  it('keeps raw text per keystroke in the list and number inputs', async () => {
    await mount(el())
    await typeKeys('cmp-roles', 'admin, ')
    expect(input('cmp-roles').value).toBe('admin, ')
    await typeKeys('cmp-roles', 'admin, aud')
    expect(input('cmp-roles').value).toBe('admin, aud')
    await typeKeys('cmp-bg-minutes', '1')
    expect(input('cmp-bg-minutes').value).toBe('1')
    await typeKeys('cmp-bg-minutes', '15')
    expect(input('cmp-bg-minutes').value).toBe('15')
  })

  it('validates days, minutes and duplicate purposes before sending', async () => {
    await mount(el())
    await click(q('add-retention'))
    await setInput(input('cmp-purposes'), 'a, a')
    await setInput(input('cmp-bg-minutes'), '4')
    await click(q('settings-save'))
    expect(putBlock).not.toHaveBeenCalled()
    const text = qa('field-error').map((e) => e.textContent).join('|')
    expect(text).toContain('Days must be a whole number from 1 to 36500.')
    expect(text).toContain('Each purpose may appear only once.')
    expect(text).toContain('Minutes must be a whole number from 5 to 240.')
    expect(q('settings-save-error')?.textContent).toContain('Fix the highlighted fields')
  })

  it('rejects days 0 and 36501 and accepts 36500', async () => {
    await mount(el())
    const days = () => document.querySelector('[data-testid="retention-row"] input[id$="-days"]') as HTMLInputElement
    for (const [v, ok] of [['0', false], ['36501', false], ['36500', true]] as const) {
      putBlock.mockClear()
      await setInput(days(), v)
      await click(q('settings-save'))
      expect(putBlock).toHaveBeenCalledTimes(ok ? 1 : 0)
    }
  })

  it('shows the keep warning and the server issues after a refused save', async () => {
    putBlock.mockRejectedValueOnce(new ApiError(422, { code: 'invalid_spec', message: 'The spec is not valid', details: [{ path: 'compliance.export_fields[0]', message: 'keep is not allowed on an identifier' }] }))
    await mount(el())
    expect(q('keep-warning')?.textContent).toContain('refused by the server')
    await setInput(input('cmp-purposes'), 'marketing, x')
    await click(q('settings-save'))
    expect(q('settings-save-error')?.textContent).toBe('The spec is not valid')
    expect(q('server-issues')?.textContent).toContain('compliance.export_fields[0]: keep is not allowed on an identifier')
  })

  it('shows validator issues for compliance after a successful save', async () => {
    issues.mockResolvedValue({ issues: [{ path: 'compliance.retention[0].entity', code: 'x', message: 'unknown entity' }, { path: 'jobs', code: 'y', message: 'other' }] })
    await mount(el())
    await setInput(input('cmp-purposes'), 'marketing, x')
    await click(q('settings-save'))
    expect(q('server-issues')?.textContent).toContain('unknown entity')
    expect(q('server-issues')?.textContent).not.toContain('other')
  })

  it('a 409 shows the conflict banner', async () => {
    putBlock.mockRejectedValueOnce(new ApiError(409, { code: 'version_conflict', message: 'stale', details: [] }))
    await mount(el())
    await setInput(input('cmp-purposes'), 'marketing, x')
    await click(q('settings-save'))
    expect(q('conflict')).not.toBeNull()
  })

  it('a never-saved block (null) loads as empty settings', async () => {
    getBlock.mockImplementation(async (_p: string, name: string) => (name === 'compliance' ? { compliance: null, version: 0 } : { regulated: null, version: 0 }))
    await mount(el())
    expect(qa('retention-row')).toHaveLength(0)
    expect((document.querySelector('[data-testid="cmp-enabled"]') as HTMLInputElement).checked).toBe(false)
    expect(q('regulated-summary')?.textContent).toContain('Not configured')
  })

  it('surfaces a settings load error and a non-object block', async () => {
    getBlock.mockImplementation(async (_p: string, name: string) => { if (name === 'compliance') throw new Error('nope'); return { regulated: null, version: 0 } })
    await mount(el())
    expect(q('settings-error')?.textContent).toContain('nope')
    getBlock.mockImplementation(async (_p: string, name: string) => (name === 'compliance' ? { compliance: 'x', version: 1 } : { regulated: null, version: 0 }))
    await click(q('settings-error')!.querySelector('button'))
    expect(q('settings-error')?.textContent).toContain('not the compliance settings')
  })

  it('viewer: read-only, no save, inputs disabled', async () => {
    role.value = 'viewer'
    await mount(el())
    expect(q('settings-readonly')).not.toBeNull()
    expect(q('settings-save')).toBeNull()
    expect(q('add-retention')).toBeNull()
    expect(input('cmp-purposes').disabled).toBe(true)
    expect((q('cmp-enabled') as HTMLInputElement).disabled).toBe(true)
  })
})

describe('Compliance page: regulated summary', () => {
  it('shows enabled, provider and protected field count, never key material', async () => {
    const host = await mount(el())
    expect(q('regulated-summary')?.textContent).toBe('StatusOnKey providerfileProtected fields2')
    expect(host.querySelector('[data-testid="compliance-regulated"] input')).toBeNull()
  })
  it('surfaces a load error', async () => {
    getBlock.mockImplementation(async (_p: string, name: string) => { if (name === 'regulated') throw new Error('denied'); return { compliance: COMPLIANCE, version: 3 } })
    await mount(el())
    expect(q('regulated-error')?.textContent).toContain('denied')
  })
})

describe('Compliance page: accessibility', () => {
  it('has no axe violations (editor with rows)', async () => {
    const host = await mount(el())
    await click(q('add-export-field'))
    await click(q('add-export-entity'))
    const res = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' ')}`)).toEqual([])
  })
  it('has no axe violations (viewer)', async () => {
    role.value = 'viewer'
    const host = await mount(el())
    const res = await axe.run(host, { rules: { 'color-contrast': { enabled: false } } })
    expect(res.violations.map((v) => v.id)).toEqual([])
  })
})
