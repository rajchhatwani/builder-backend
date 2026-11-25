export const id = 'd9822adc-48cc-4db6-a2d2-ddeb4b377b39'
export const time = '2026-01-15T12:00:00Z'
export const labels = {
  documents: ['Documents', 'Documents', 'Reviewed invoice', 'No documents match these filters.'],
  agentactions: ['Agent actions', 'AI action approvals', 'intake proposes record_request', 'No proposals match these filters.'],
  places: ['Places', 'Places & fences', 'Central warehouse', 'No places found.'],
  matching: ['Matching', 'Matching', 'Request 21', 'No assignments match these filters.'],
  prediction: ['Prediction', 'Prediction', 'Trip 21', 'No predictions recorded yet.'],
  routing: ['Routing', 'Route, ETA and geocode', '40.250000', 'Enter an address to look up its coordinates.'],
} as const
export type Screen = keyof typeof labels
export const paths: Record<Screen, string> = {
  documents: '/ai/documents', agentactions: '/ai/agents/proposals', places: '/geo/places',
  matching: '/matching/assignments', prediction: '/prediction/records', routing: '/geo/geocode',
}
const document = {
  id, title: 'Reviewed invoice', kind: 'invoice', status: 'needs_review', created_by: 'uploader', reviewed_by: null,
  created_at: time, updated_at: time, reviewed_at: null, content: 'Balance USD 54', reject_reason: null, call_id: null,
  fields: [{ name: 'total', value: '54', confidence_bp: 6000, anchor: { page: 1, start: 12, end: 14, quote: '54' },
    corrected: false, original_value: null, review_required: true }],
}
const proposal = {
  id, run_id: id, agent: 'intake', action: 'record_request', kind: 'note', risk: 'medium', args: { subject: 'Request 21' },
  allowed_autonomy: 'draft', status: 'pending_approval', reason: null, result: null, error_code: null, executed_by: null,
  decided_by: null, decided_at: null, note: null, handoff_role: null, outcome: null, outcome_by: null, outcome_at: null, created_at: time,
}
const point = { lat: '40.250000', lng: '-73.000000', lat_micro: 40250000, lng_micro: -73000000 }
const place = { ...point, id, name: 'Central warehouse', kind: 'warehouse', created_at: time }
const assignment = { id, request_ref: 'Request 21', candidate_id: 'Courier 9', status: 'offered', score: 500, distance_m: 390, offered_at: time, expires_at: time, decided_at: null }
const prediction = { id, kind: 'delivery', subject_ref: 'Trip 21', model_id: 'fake', unit: 'minutes', value: 10, low: 8, high: 12,
  actual: null, actual_at: null, created_at: time, features: { distance_m: 390 } }
const page = (items: unknown[]) => ({ items, total: items.length, limit: 20, offset: 0 })
export function runtimeFixture(path: string, empty = false): unknown {
  switch (path) {
    case '/ai/documents': return page(empty ? [] : [document])
    case '/ai/documents/' + id: return document
    case '/ai/agents/proposals': return page(empty ? [] : [proposal])
    case '/ai/agents/proposals/' + id: return proposal
    case '/ai/agents/stats': return { agents: empty ? [] : [{ agent: 'intake', runs: 1, proposals: 1, executed: 0, rejected: 0, pending: 1,
      outcome_success: 0, outcome_failure: 0, outcome_neutral: 0, success_rate_bp: null }] }
    case '/ai/agents': return { agents: [], actions: [] }
    case '/ai/agents/runs': return page([])
    case '/geo/geofences': return page([])
    case '/geo/events': return page([])
    case '/geo/places': return page(empty ? [] : [place])
    case '/geo/places/' + id: return place
    case '/location/positions': return { items: [], truncated: false }
    case '/matching/assignments': return page(empty ? [] : [assignment])
    case '/matching/assignments/' + id: return assignment
    case '/matching/assignments/' + id + '/reject': return { ...assignment, status: 'rejected' }
    case '/prediction/records': return page(empty ? [] : [prediction])
    case '/prediction/predict': return prediction
    case '/prediction/records/' + id: return prediction
    case '/prediction/records/' + id + '/actual': return { ...prediction, actual: 11, actual_at: time }
    case '/prediction/stats': return { logged: empty ? 0 : 1, with_actual: 0, mae_milli: null, abs_error_sum: 0, covered: 0, coverage_bp: null }
    case '/geo/geocode': return { ...point, provider: 'fake' }
    case '/geo/route': return { distance_m: 700, duration_s: 50, mode: 'drive', provider: 'fake' }
  }
}
export const pdf = { id: 'invoice', title: 'Invoice template', kind: 'invoice', entity: null, compute: 'items',
  roles: ['admin'], template: { page: { size: 'A4', orientation: 'portrait' }, blocks: [{ type: 'heading', level: 1, text: 'Invoice' }] } }
export const library = [{ id: 'invoice', title: 'Invoice template', industries: ['Retail'], why: 'Send an invoice for a sale.',
  compute: 'items', template: pdf.template, sample: { items: [{ name: 'Repairs', quantity: 1 }] } }]

export function builderFixture(path: string, root: string, projectId: string, empty = false): unknown {
  if (path === root + '/documents') return { project_id: projectId, enabled: !empty, rate_limit: '30/minute',
    templates: empty ? [] : [pdf], version: empty ? 0 : 3, updated_at: empty ? null : time }
  if (path === root + '/documents/library') return library
  if (path === root + '/documents/issues') return { issues: [] }
  if (path === root + '/behavior/packs') return { packs: { ai: { documents: { review_below_bp: 8000, max_text_chars: 200_000,
    kinds: [{ name: 'invoice', fields: [{ name: 'total', required: true }] }] } } }, version: 2, row_version: 2, updated_at: time }
}
