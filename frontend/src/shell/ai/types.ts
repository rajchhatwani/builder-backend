/** Hand-written types for the builder-agent endpoints (app/schemas/agent_run.py, agent_approval.py) and the
 *  requirements API (contract agreed with the backend; align to app/schemas when it lands). */

export interface Run {
  id: string
  project_id: string
  workspace_id: string | null
  goal: string
  state: string
  phase: string
  budgets: Record<string, unknown>
  steps_used: number
  repairs_used: number
  cost_micro_usd: number
  stop_code: string | null
  stop_detail: string | null
  /** Set when a person asked the run to stop at its next step (POST .../pause). */
  paused_at?: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

export interface Step {
  id: string
  seq: number
  kind: string
  tool_name: string | null
  tool_call_id: string | null
  state: string
  ok: boolean
  input: Record<string, unknown> | null
  output: Record<string, unknown> | null
  model: string | null
  created_at: string
}

export interface RunDetail extends Run {
  steps: Step[]
  steps_total: number
  limit: number
  offset: number
}

export interface RunPage { items: Run[]; total: number; limit: number; offset: number }

export interface Approval {
  id: string
  run_id: string
  project_id: string
  kind: string
  subject: string
  payload: Record<string, unknown>
  risk_flags: string[]
  state: string
  requires_owner: boolean
  bound_spec_hash: string
  bound_commit?: string | null
  payload_hash?: string | null
  decided_by?: string | null
  decided_at: string | null
  decision_note: string | null
  expires_at: string
  created_at: string
}

/** GET /orgs/{slug}/ai/platform-budget. cap and remaining are null when no cap is configured. */
export interface PlatformBudget {
  cap_micro_usd: number | null
  spent_micro_usd: number
  reserved_micro_usd: number
  remaining_micro_usd: number | null
}

/** app/schemas/preview.py */
export interface Preview {
  id: string
  project_id: string
  workspace_id: string | null
  state: string
  spec_hash: string
  url_path: string
  error: string | null
  created_at: string
  last_request_at: string
  expires_at: string
  limits: Record<string, unknown>
  is_preview: boolean
}
export interface PreviewCreated extends Preview { token: string }

export type ItemStatus = 'open' | 'covered' | 'out_of_scope' | string
export interface RequirementItem {
  id: string
  kind: string
  text: string
  source_doc: string | null
  source_page: number | null
  source_section: string | null
  status: ItemStatus
  covered_by: string | null
}
export interface RequirementQuestion {
  id: string
  text: string
  assumption: string | null
  answer: string | null
  state: 'open' | 'answered' | 'assumed' | string
}
export interface RequirementsMap {
  id: string
  status: string
  items: RequirementItem[]
  questions: RequirementQuestion[]
  sources: Array<{ name: string; kind: string; pages: number; chunks: number; chars: number }>
  coverage?: { total: number; open: number; covered: number; out_of_scope: number; percent_covered: number; open_questions: number }
  phases?: Array<{ number: number; name: string; kinds: string[]; items: number }>
}

/** POST /agent/runs/{id}/gates: failures are generic rows (rule_id, location, expected, actual, hint); render by key, never by id. */
export interface GateRunResult {
  ok: boolean
  failure_count: number
  failures: Record<string, string>[]
  report_hash: string
}
