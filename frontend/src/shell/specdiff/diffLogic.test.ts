import { describe, expect, it } from 'vitest'
import { MAX_ITEMS, REDACTED, baselineKey, changeText, clearBaseline, diffSpecs, loadBaseline, parseSpecText, saveBaseline } from './diffLogic'

const BASE = {
  spec_version: 1,
  project: { name: 'Shop', slug: 'shop' },
  entities: [
    { name: 'Customer', table_name: 'customers', fields: [{ name: 'email', type: 'string', required: true }] },
    { name: 'Invoice', table_name: 'invoices', options: { soft_delete: false }, fields: [{ name: 'amount', type: 'int', required: false }, { name: 'note', type: 'string' }] },
    { name: 'Legacy', table_name: 'legacy', fields: [] },
  ],
  relations: [{ kind: 'many_to_one', from_entity: 'Invoice', to_entity: 'Customer', from_name: 'customer', to_name: 'invoices', on_delete: 'restrict' }],
  auth: {
    enabled: true,
    access_token_ttl_minutes: 15,
    roles: [{ name: 'clerk', label: 'Clerk' }, { name: 'boss', label: 'Boss' }],
    permissions: [{ entity: 'Invoice', operation: 'update', roles: ['boss'] }],
    smtp_password: 'old-value',
  },
  state_machines: [{ entity: 'Invoice', field: 'status', initial: 'draft', transitions: [{ name: 'send', from_states: ['draft'], to_state: 'sent' }] }],
  authorization: { model: 'rbac', policies: [{ id: 'p1', effect: 'allow', actions: ['Invoice.*'] }] },
  hooks: [{ name: 'check_total', point: 'Invoice.validate', kind: 'pure' }],
  deployment: { cloud: 'aws', region: 'eu-west-1' },
}

const CUR = {
  ...BASE,
  entities: [
    { name: 'Customer', table_name: 'customers', fields: [{ name: 'email', type: 'string', required: true }, { name: 'phone', type: 'string' }] },
    { name: 'Invoice', table_name: 'invoices', options: { soft_delete: true }, fields: [{ name: 'amount', type: 'decimal', required: true }] },
    { name: 'Order', table_name: 'orders', fields: [] },
  ],
  relations: [],
  auth: {
    ...BASE.auth,
    roles: [{ name: 'clerk', label: 'Clerk' }, { name: 'auditor', label: 'Auditor' }],
    permissions: [{ entity: 'Invoice', operation: 'update', roles: ['boss', 'clerk'] }],
    smtp_password: 'new-value',
  },
  state_machines: [{ entity: 'Invoice', field: 'status', initial: 'draft', transitions: [{ name: 'send', from_states: ['draft', 'review'], to_state: 'sent' }, { name: 'void', from_states: ['sent'], to_state: 'void' }] }],
  authorization: { model: 'rbac', policies: [{ id: 'p1', effect: 'deny', actions: ['Invoice.*'] }, { id: 'p2', effect: 'allow', actions: ['*'] }] },
  hooks: [],
  deployment: { cloud: 'aws', region: 'us-east-1' },
}

describe('diffSpecs', () => {
  it('builds the exact diff model for two fixture specs', () => {
    expect(diffSpecs(BASE, CUR)).toEqual({
      total: 13,
      truncated: false,
      sections: [
        {
          id: 'entities',
          label: 'Entities and fields',
          items: [
            { kind: 'changed', key: 'Customer', changes: [{ kind: 'added', label: 'field phone' }] },
            {
              kind: 'changed',
              key: 'Invoice',
              changes: [
                { kind: 'changed', label: 'options.soft_delete', before: 'false', after: 'true' },
                { kind: 'changed', label: 'field amount · required', before: 'false', after: 'true' },
                { kind: 'changed', label: 'field amount · type', before: 'int', after: 'decimal' },
                { kind: 'removed', label: 'field note' },
              ],
            },
            { kind: 'removed', key: 'Legacy', changes: [] },
            { kind: 'added', key: 'Order', changes: [] },
          ],
        },
        { id: 'relations', label: 'Relations', items: [{ kind: 'removed', key: 'Invoice.customer -> Customer.invoices', changes: [] }] },
        {
          id: 'roles',
          label: 'Roles',
          items: [
            { kind: 'added', key: 'auditor', changes: [] },
            { kind: 'removed', key: 'boss', changes: [] },
          ],
        },
        {
          id: 'permissions',
          label: 'Permissions',
          items: [{ kind: 'changed', key: 'Invoice.update', changes: [{ kind: 'changed', label: 'roles', before: 'boss', after: 'boss, clerk' }] }],
        },
        {
          id: 'machines',
          label: 'State machines',
          items: [
            {
              kind: 'changed',
              key: 'Invoice.status',
              changes: [
                { kind: 'changed', label: 'transition send · from_states', before: 'draft', after: 'draft, review' },
                { kind: 'added', label: 'transition void' },
              ],
            },
          ],
        },
        {
          id: 'rules',
          label: 'Rules and policies',
          items: [
            { kind: 'changed', key: 'policy p1', changes: [{ kind: 'changed', label: 'effect', before: 'allow', after: 'deny' }] },
            { kind: 'added', key: 'policy p2', changes: [] },
          ],
        },
        { id: 'hooks', label: 'Hooks', items: [{ kind: 'removed', key: 'check_total', changes: [] }] },
        {
          id: 'other',
          label: 'Other settings',
          items: [
            {
              kind: 'changed',
              key: 'other settings',
              changes: [
                { kind: 'changed', label: 'auth.smtp_password', redacted: true },
                { kind: 'changed', label: 'deployment.region', before: 'eu-west-1', after: 'us-east-1' },
              ],
            },
          ],
        },
      ],
    })
  })

  it('is empty for identical specs', () => {
    expect(diffSpecs(BASE, JSON.parse(JSON.stringify(BASE)))).toEqual({ total: 0, truncated: false, sections: [] })
  })

  it('is stable: item order does not depend on list order', () => {
    const shuffled = { ...CUR, entities: [...CUR.entities].reverse() }
    expect(diffSpecs(BASE, shuffled)).toEqual(diffSpecs(BASE, CUR))
  })

  it('never shows values of secret-looking paths', () => {
    const text = JSON.stringify(diffSpecs(BASE, CUR))
    expect(text).not.toContain('old-value')
    expect(text).not.toContain('new-value')
    const secret = diffSpecs(BASE, CUR).sections.find((s) => s.id === 'other')!.items[0].changes[0]
    expect(changeText(secret)).toBe(`~ auth.smtp_password: ${REDACTED}`)
  })

  it('caps the output size and says so', () => {
    const many = Array.from({ length: MAX_ITEMS + 25 }, (_, i) => ({ name: `E${String(i).padStart(4, '0')}`, fields: [] }))
    const m = diffSpecs({ entities: [] }, { entities: many })
    expect(m.total).toBe(MAX_ITEMS + 25)
    expect(m.sections[0].items).toHaveLength(MAX_ITEMS)
    expect(m.truncated).toBe(true)
  })

  it('formats change lines with a text marker', () => {
    expect(changeText({ kind: 'added', label: 'field phone' })).toBe('+ field phone')
    expect(changeText({ kind: 'removed', label: 'field note', before: 'x' })).toBe('- field note: x')
    expect(changeText({ kind: 'changed', label: 'type', before: 'int', after: 'decimal' })).toBe('~ type: int -> decimal')
  })
})

describe('parseSpecText', () => {
  it('accepts an object, refuses empty, broken and non-object JSON', () => {
    expect(parseSpecText('{"a":1}')).toEqual({ ok: true, spec: { a: 1 } })
    expect(parseSpecText('  ').ok).toBe(false)
    expect(parseSpecText('{oops').ok).toBe(false)
    expect(parseSpecText('[1]')).toEqual({ ok: false, error: 'A spec must be a JSON object.' })
  })
})

describe('baseline storage', () => {
  const mem = () => {
    const m = new Map<string, string>()
    return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k) }
  }
  it('saves per project with a timestamp, loads it back and clears it', () => {
    const s = mem()
    const saved = saveBaseline(s, 'p1', { a: 1 }, new Date('2026-11-09T10:00:00Z'))
    expect(saved).toEqual({ savedAt: '2026-11-09T10:00:00.000Z', spec: { a: 1 } })
    expect(s.getItem(baselineKey('p1'))).not.toBeNull()
    expect(baselineKey('p1')).toBe('bb.specBaseline.p1')
    expect(loadBaseline(s, 'p1')).toEqual(saved)
    expect(loadBaseline(s, 'p2')).toBeNull()
    clearBaseline(s, 'p1')
    expect(loadBaseline(s, 'p1')).toBeNull()
  })
  it('treats corrupt or unavailable storage as no baseline', () => {
    const s = mem()
    s.setItem(baselineKey('p'), '{bad')
    expect(loadBaseline(s, 'p')).toBeNull()
    const broken = { getItem: () => { throw new Error('x') }, setItem: () => { throw new Error('x') }, removeItem: () => { throw new Error('x') } }
    expect(loadBaseline(broken, 'p')).toBeNull()
    expect(saveBaseline(broken, 'p', {})).toBeNull()
    expect(() => clearBaseline(broken, 'p')).not.toThrow()
  })
})
