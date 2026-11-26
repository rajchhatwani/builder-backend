export const projectId = '95ff34eb-4d07-4a60-8669-aaf1cf5442ca'
export const projectRoot = '/projects/' + projectId
export const now = '2026-08-20T09:00:00Z'
export const user = {
  id: 'fixture-user', name: 'Mina Chen', email: 'mina@example.test', platform_role: 'customer', email_verified_at: now,
}
export const options = {
  operations: ['list', 'get', 'head', 'create', 'replace', 'update', 'delete'],
  filterable: ['status'], sortable: ['title'], searchable: ['title'], default_page_size: 20, max_page_size: 100, soft_delete: false,
}
export const entities = [
  { id: 'e-1', name: 'Ticket', plural_path: 'tickets', table_name: 'tickets', options, project_id: projectId, created_at: now, updated_at: now },
  { id: 'e-2', name: 'Comment', plural_path: 'comments', table_name: 'comments', options: { ...options, filterable: [], sortable: [], searchable: [] }, project_id: projectId, created_at: now, updated_at: now },
]
const field = { entity_id: 'e-1', created_at: now, updated_at: now, required: false, unique: false, indexed: false, default: null, max_length: null, min_value: null, max_value: null, enum_values: null }
export const fields = [
  { ...field, position: 0, id: 'f-1', name: 'title', type: 'string', required: true, max_length: 120 },
  { ...field, position: 1, id: 'f-2', name: 'status', type: 'enum', required: true, default: 'open', enum_values: ['open', 'closed', 'archived'] },
  { ...field, position: 2, id: 'f-3', name: 'api_secret', type: 'string' },
]
export const relation = {
  project_id: projectId, id: 'r-1', from_entity_id: 'e-1', to_entity_id: 'e-2',
  from_name: 'comments', to_name: 'ticket', kind: 'one_to_many', on_delete: 'restrict', required: true, created_at: now, updated_at: now,
}
export const history = [{ entity: 'Ticket', fields: ['title'], retention_days: 90, view_roles: ['staff'] }]
export const machines = [{
  entity: 'Ticket', field: 'status', initial: 'open',
  transitions: [{ name: 'close_ticket', from_states: ['open'], to_state: 'closed', roles: ['staff'], when: 'title != ""', auto: false }],
}]
export const spec = {
  entities: entities.map((entity, index) => ({ name: entity.name, table_name: entity.table_name, plural_path: entity.plural_path, options: entity.options, fields: index ? [] : fields })),
  relations: [{ ...relation, from_entity: 'Ticket', to_entity: 'Comment' }],
  auth: { enabled: true, roles: [{ name: 'staff', label: 'Staff' }, { name: 'reader', label: 'Reader' }],
    permissions: [{ entity: 'Ticket', operation: 'list', roles: ['staff'], row_rule: null }] },
  authorization: { model: 'rbac', field_access: [] },
  state_machines: machines,
  history,
}
export const op = {
  id: 'op-2', project_id: projectId, seq: 2, op_type: 'add_entity', origin: 'do', ref_seq: null,
  actor: { kind: 'user', user_id: user.id, email: user.email }, payload: { entity: { name: 'Comment' } },
  inverse: { op_type: 'remove_entity', payload: { name: 'Comment' } },
  spec_hash_before: 'example-before', spec_hash_after: 'example-after', created_at: now,
}
const list = <T>(items: T[]) => ({ items, limit: 200, offset: 0, total: items.length })
const matrix = {
  entities: ['Ticket', 'Comment'], roles: ['staff', 'reader', '(public)'],
  cells: ['object', 'row', 'field'].flatMap(layer => ['staff', 'reader', '(public)'].map(role => ({
    layer, entity: 'Ticket', target: layer === 'field' ? 'title.read' : 'list', role, value: role === 'staff' ? 'yes' : 'no',
  }))),
}
export const accessDiff = {
  changes: [{ layer: 'object', entity: 'Ticket', target: 'list', role: 'reader', before: 'no', after: 'yes', effect: 'gain' }],
  roles_gaining: { reader: ['Ticket.list'] }, roles_losing: {}, weakens: true,
  counts: { gain: 1, lose: 0, change: 0, added: 0, removed: 0 },
  renames: [], unprotected_entities: [],
}
export const sections = ['model', 'machines', 'permissions', 'specdiff', 'timeline', 'history'] as const
export type Screen = typeof sections[number]

export const pendingPaths: Record<Screen, string> = {
  model: '/entities', machines: '/behavior/state-machines', permissions: '/access/matrix',
  specdiff: '/spec', timeline: '/spec/ops', history: '/behavior/history',
}
export const expectations = {
  model: { normal: 'Ticket', empty: 'Add your first entity' },
  machines: { normal: 'close_ticket', empty: 'No state machines yet' },
  permissions: { normal: 'Edit access', empty: 'No entities to show' },
  specdiff: { normal: '1 difference', empty: 'No baseline to compare with' },
  timeline: { normal: 'Version 2 · Added entity Comment', empty: 'No changes recorded' },
  history: { normal: 'Fields to record', empty: 'No change history yet' },
}
export const desktop = new Set<Screen>(['model', 'machines', 'permissions', 'specdiff'])

export function fixture(path: string, role = 'editor', empty = false) {
  if (path === '/account/refresh') return { access_token: 'fixture' }
  if (path === '/account/me') return user
  if (path === '/orgs') return list([{ id: 'org', name: 'Support Co', slug: 'support', kind: 'team' }])
  if (path === '/entities/e-1/fields') return list(fields)
  if (path === '/entities/e-2/fields') return list([])
  if (!path.startsWith(projectRoot)) return undefined
  const section = path.slice(projectRoot.length)
  switch (section) {
    case '': return { id: projectId, name: 'Support desk', organization_id: 'org', version: 5 }
    case '/status': return { ready: true, issues: [], counts: {}, sections: [] }
    case '/members': return [{ user_id: user.id, name: user.name, email: user.email, role, mcp_enabled: false }]
    case '/entities': return list(empty ? [] : entities)
    case '/relations': return list(empty ? [] : [relation])
    case '/spec': return empty ? { entities: [] } : spec
    case '/spec/at/1': return { ...spec, entities: spec.entities.slice(0, 1) }
    case '/spec/at/0': return { entities: [] }
    case '/spec/ops': return list(empty ? [] : [op, { ...op, id: 'op-1', seq: 1, payload: { entity: { name: 'Ticket' } } }])
    case '/access/matrix': return empty ? { cells: [], roles: [], entities: [] } : matrix
    case '/access/diff': return accessDiff
    case '/behavior/state-machines': return { project_id: projectId, version: 3, updated_at: now, state_machines: empty ? [] : machines }
    case '/behavior/history': return { project_id: projectId, version: 4, updated_at: now, history: empty ? [] : history }
    case '/behavior/issues': return { issues: [] }
    case '/behavior/roles': return { roles: spec.auth.roles }
    case '/generations': return list([])
    case '/previews': return []
    default: return undefined
  }
}
