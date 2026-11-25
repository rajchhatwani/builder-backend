import { expect, it } from 'vitest'
import { permissionReducer, reviewReducer, type AuthorizationEdit, type PermissionChange } from './access'
import { blockDraftReducer, defaultCompliance } from './compliance'
import { conditionBody, conditionDraft, policyReducer } from './policy'

it('retains the exact authorization edit awaiting confirmation', () => {
  const edit: AuthorizationEdit = { kind: 'settings', settings: {
    project_id: 'project', model: 'rbac', version: 4, policies: [], field_access: [], attachments: {}, updated_at: null,
  } }
  const review = reviewReducer(null, { type: 'review', edit })
  expect(review).toEqual({ edit, confirm: false, removePolicies: true })
  expect(reviewReducer(review, { type: 'confirm', edit })).toEqual({ edit, confirm: true, removePolicies: false })
})

it('keeps unapplied permissions when a batch partially succeeds', () => {
  const change: PermissionChange = { current: undefined, value: { entity_id: 'employee', operation: 'get', roles: ['member'] } }
  let state = permissionReducer({}, { type: 'stage', key: 'employee:get', change })
  state = permissionReducer(state, { type: 'stage', key: 'employee:list', change: { ...change, value: null } })
  expect(permissionReducer(state, { type: 'applied', keys: ['employee:get'] })).toEqual({
    'employee:list': { current: undefined, value: null },
  })
})

it('keeps a compliance draft on its original version until reset', () => {
  const initial = { base: defaultCompliance, draft: defaultCompliance, version: 2, revision: 0 }
  const state = blockDraftReducer(initial, { type: 'edit', apply: draft => ({ ...draft, enabled: true }) })
  expect(state).toEqual({ ...initial, draft: { ...defaultCompliance, enabled: true } })
  expect(blockDraftReducer(state, { type: 'reset', value: defaultCompliance, version: 3 })).toEqual({ ...initial, version: 3, revision: 1 })
})

it('keeps a nested policy condition lossless and changes only the policy draft', () => {
  const node = { any: [{ left: { subject: 'roles' }, op: 'contains', right: { literal: 'admin' } },
    { all: [{ left: { resource: 'status' }, op: 'is_null' }] }] }
  const when = conditionDraft(node)
  expect(conditionBody(when)).toEqual(node)
  const base = { project_id: 'project', model: 'abac' as const, policies: [], attachments: {}, field_access: [], version: 4, updated_at: null }
  const policy = { id: 'admin_only', effect: 'allow' as const, description: '', when, actions: ['Employee.get'] }
  const draft = policyReducer(null, { type: 'open', draft: { base, policy } })
  expect(policyReducer(draft, { type: 'change', value: { description: 'Allow admin' } }))
    .toEqual({ base, policy: { ...policy, description: 'Allow admin' } })
})
