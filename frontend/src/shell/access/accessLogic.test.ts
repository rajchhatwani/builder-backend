import { describe, expect, it } from 'vitest'
import type { AccessCell, AccessDiff, AccessMatrix, AuthorizationSettings } from '../../api/types'
import { authorizationWriteBody } from './authorizationBody'
import { fieldAccessOf, fieldNames, groupTable, permissionsRequest, setFieldRoles, summariseDiff, toggleRole, withEdits } from './accessLogic'

const c = (layer: AccessCell['layer'], entity: string, target: string, role: string, value: string): AccessCell => ({ layer, entity, target, role, value })
export const MATRIX: AccessMatrix = {
  roles: ['admin', 'clerk', '(public)'],
  entities: ['Invoice', 'Note'],
  cells: [
    c('object', 'Invoice', 'update', 'admin', 'yes'),
    c('object', 'Invoice', 'list', 'admin', 'yes'),
    c('object', 'Invoice', 'list', 'clerk', 'yes'),
    c('object', 'Invoice', 'update', 'clerk', 'no'),
    c('object', 'Invoice', 'list', '(public)', 'no'),
    c('object', 'Note', 'list', 'admin', 'yes'),
    c('field', 'Invoice', 'amount.read', 'admin', 'yes'),
    c('field', 'Invoice', 'amount.write', 'admin', 'yes'),
    c('field', 'Invoice', 'amount.read', 'clerk', 'no'),
    c('row', 'Invoice', 'list', 'admin', 'all'),
    c('row', 'Invoice', 'list', 'clerk', 'own'),
  ],
}

describe('groupTable', () => {
  it('groups object cells by role x operation in operation order', () => {
    const t = groupTable(MATRIX, 'object', 'Invoice')
    expect(t.targets).toEqual(['list', 'update'])
    expect(t.roles).toEqual(['admin', 'clerk', '(public)'])
    expect(t.values.clerk).toEqual({ list: 'yes', update: 'no' })
    expect(t.values['(public)']).toEqual({ list: 'no' })
  })
  it('keeps field targets in order of appearance and ignores other entities and layers', () => {
    const t = groupTable(MATRIX, 'field', 'Invoice')
    expect(t.targets).toEqual(['amount.read', 'amount.write'])
    expect(t.values.clerk['amount.write']).toBeUndefined()
    expect(groupTable(MATRIX, 'row', 'Invoice').values.clerk).toEqual({ list: 'own' })
    expect(groupTable(MATRIX, 'row', 'Note').targets).toEqual([])
    expect(fieldNames(MATRIX, 'Invoice')).toEqual(['amount'])
  })
})

describe('summariseDiff', () => {
  const diff: AccessDiff = {
    changes: [
      { layer: 'object', entity: 'Invoice', target: 'update', role: 'clerk', before: 'no', after: 'yes', effect: 'gain' },
      { layer: 'object', entity: 'Invoice', target: 'list', role: 'admin', before: 'yes', after: 'no', effect: 'lose' },
    ],
    roles_gaining: { clerk: ['Invoice.update'] },
    roles_losing: { admin: ['Invoice.list', 'Invoice.get'] },
    weakens: true,
    counts: { gain: 1, lose: 1, change: 0, added: 0, removed: 0 },
  }
  it('lists gains and losses exactly as the API body names them', () => {
    const s = summariseDiff(diff)
    expect(s.gains).toEqual([{ role: 'clerk', targets: diff.roles_gaining.clerk }])
    expect(s.losses).toEqual([{ role: 'admin', targets: diff.roles_losing.admin }])
    expect(s.lines).toEqual(['Role clerk gains Invoice.update', 'Role admin loses Invoice.list, Invoice.get'])
    expect(s.weakens).toBe(true)
    expect(s.total).toBe(2)
  })
})

describe('edits', () => {
  it('toggleRole adds, removes and creates rules without mutating', () => {
    const rules = [{ entity: 'Invoice', operation: 'update', roles: ['admin'] }]
    expect(toggleRole(rules, 'Invoice', 'update', 'clerk', true)[0].roles).toEqual(['admin', 'clerk'])
    expect(toggleRole(rules, 'Invoice', 'update', 'admin', false)[0].roles).toEqual([])
    expect(toggleRole(rules, 'Invoice', 'list', 'clerk', true)).toHaveLength(2)
    expect(toggleRole(rules, 'Invoice', 'list', 'clerk', false)).toBe(rules)
    expect(rules[0].roles).toEqual(['admin'])
  })
  it('setFieldRoles drops a rule with both lists null', () => {
    const one = setFieldRoles([], 'Invoice', 'amount', { read_roles: ['admin'], write_roles: null })
    expect(one).toEqual([{ entity: 'Invoice', field: 'amount', read_roles: ['admin'], write_roles: null }])
    expect(setFieldRoles(one, 'Invoice', 'amount', { read_roles: null, write_roles: null })).toEqual([])
  })
  it('builds a diff request that keeps the other layer and a spec that keeps everything else', () => {
    const rules = [{ entity: 'Invoice', operation: 'list', roles: ['admin'] }]
    expect(permissionsRequest(rules)).toEqual({ permissions: rules, field_access: null })
    const spec = { auth: { roles: [1], permissions: [] }, authorization: { model: 'rbac', field_access: [] }, entities: [] }
    const next = withEdits(spec, permissionsRequest(rules))
    expect(next.auth).toEqual({ roles: [1], permissions: rules })
    expect(next.authorization).toBe(spec.authorization)
    expect(spec.auth.permissions).toEqual([])
    expect(fieldAccessOf(next)).toEqual([])
  })
})

describe('authorization save round trip', () => {
  it('sends the loaded field_access back unchanged when policies are saved', () => {
    const settings: AuthorizationSettings = {
      project_id: 'p', model: 'pbac', policies: [], attachments: {}, version: 4, updated_at: null,
      field_access: [{ entity: 'Invoice', field: 'amount', read_roles: ['admin'], write_roles: null }],
    }
    const body = authorizationWriteBody(settings, { policies: [{ id: 'x', description: '', effect: 'allow', actions: [], when: null }] })
    expect(body.field_access).toEqual(settings.field_access)
    expect(body.model).toBe('pbac')
    expect(body.expected_version).toBe(4)
    expect(body.policies).toHaveLength(1)
  })
})
