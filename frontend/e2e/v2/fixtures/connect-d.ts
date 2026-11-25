import { packs, packSpec } from './connect-c'

const admin = ['admin']
const member = ['member']
export const advancedPacks = {
  ...packs,
  operations: { ...packs.operations,
    matching: { read_roles: member, assign_roles: admin, weights: { distance: 1000, load: 200, rating: 0 },
      max_distance_m: 20000, max_load: 10, offer_ttl_seconds: 300 },
    prediction: { read_roles: member, write_roles: admin, model_id: 'fake-linear-v1', unit: 'days', interval_bp: 2000 },
  },
  ai: {
    gateway: { region: 'eu', zero_retention: false,
      providers: [{ name: 'local', kind: 'fake', byo_key_env: null }],
      stages: [{ name: 'answer', provider: 'local', model: 'fake-small', max_output_tokens: 512, fallback_model: null },
        { name: 'extract', provider: 'local', model: 'fake-small', max_output_tokens: 512, fallback_model: null }],
      budget: { period: 'day', limit_micro_usd: 1_000_000, per_call_cap_micro_usd: 100_000 },
      roles: { call_roles: member, read_roles: member, manage_roles: admin },
    },
    documents: { stage: 'extract', kinds: [{ name: 'invoice', fields: [{ name: 'total', required: true }] }],
      upload_roles: member, review_roles: admin, read_roles: member, review_below_bp: 8000, max_text_chars: 200000,
      allow_self_review: false },
    knowledge: { stage: 'answer', manage_roles: admin, read_roles: member, chunk_chars: 800, max_sources: 1000,
      max_text_chars: 500000 },
    agents: { actions: [{ name: 'note', kind: 'note', description: 'Summarize the request.', risk: 'low',
      max_autonomy: 'draft', entity: null, fields: [] }],
      agents: [{ name: 'assistant', stage: 'answer', actions: ['note'], autonomy: 'suggest', max_actions_per_run: 5,
        require_eval: 'basic' }],
      roles: { run_roles: member, approve_roles: admin, read_roles: member }, allow_self_approval: false },
    evals: { suites: [{ name: 'basic', agent: 'assistant', pass_bp: 8000, cases: [
      { name: 'Summarize', goal: 'Summarize the submitted request.', expect_actions: ['note'], forbid_actions: [] },
    ] }], run_roles: admin },
  },
}
export const advancedPackSpec = { ...packSpec, auth: { ...packSpec.auth, provider: 'builtin' },
  entities: [{ name: 'Ticket', table_name: 'tickets', fields: [{ name: 'summary', required: true, type: 'string' }] }] }

export const advancedScreens = {
  matchingsettings: { title: 'Matching settings', normal: 'Score weights', path: ['operations', 'matching'] },
  predictionsettings: { title: 'Prediction settings', normal: 'Prediction records', path: ['operations', 'prediction'] },
  aigatewaysettings: { title: 'AI gateway settings', normal: 'Data handling', path: ['ai', 'gateway'] },
  aidocssettings: { title: 'AI documents settings', normal: 'Extraction and review', path: ['ai', 'documents'] },
  knowledgesettings: { title: 'Knowledge settings', normal: 'Source limits', path: ['ai', 'knowledge'] },
  agentssettings: { title: 'AI agents settings', normal: 'Approval policy', path: ['ai', 'agents'] },
  evalssettings: { title: 'AI evals settings', normal: 'Suite 1', path: ['ai', 'evals'] },
} as const
