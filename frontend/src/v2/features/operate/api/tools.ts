import { segment } from './live'

export const documentsPath = '/ai/documents'
export const documentPath = (id: string) => `/ai/documents/${segment(id)}` as const
export const proposalPath = (id: string) => `/ai/agents/proposals/${segment(id)}` as const
export const runPath = (id: string) => `/ai/agents/runs/${segment(id)}` as const
export const recordPath = (id: string) => `/prediction/records/${segment(id)}` as const
export const assignmentPath = (id: string) => `/matching/assignments/${segment(id)}` as const
export const geoPath = (collection: 'places' | 'geofences', id: string) => `/geo/${collection}/${segment(id)}` as const
export const positionPath = (id: string) => `/location/positions/${segment(id)}` as const

export type Point = { lat_micro: number; lng_micro: number }
export type Coordinates = Point & { lat: string; lng: string }

export type Place = Coordinates & { id: string; name: string; kind: string | null; created_at: string }
export type PlaceHits = { items: (Place & { distance_m: number })[]; truncated: boolean }
export type Fence = {
  id: string; name: string; shape: 'circle' | 'polygon'; center: Coordinates | null; radius_m: number | null
  vertices: Coordinates[] | null; created_at: string
}
export type FenceEvent = Point & { id: string; subject_id: string; geofence_id: string; geofence_name: string; event: string; occurred_at: string }
export type Position = Coordinates & { subject_id: string; subject_kind: string; seq: string | number; recorded_at: string; updated_at: string }
export type Positions = { items: Position[]; truncated: boolean }
export type PositionHistory = { items: { seq: string | number; recorded_at: string; point: Coordinates }[]; retention_cap: number }

export type RouteMode = 'drive' | 'walk' | 'bike'
export type Geocode = Coordinates & { provider: string }
export type RouteResult = { distance_m: number; duration_s?: number; mode?: RouteMode; provider?: string; arrives_at?: string }
export type RouteBody = { origin: Point; destination: Point; mode: RouteMode; depart_at?: string } | { a: Point; b: Point }

export type Prediction = {
  id: string; kind: string; subject_ref: string; model_id: string; unit: string
  value: number; low: number; high: number; features: Record<string, unknown>
  actual: number | null; actual_at: string | null; created_at: string
}
export type PredictionStats = { logged: number; with_actual: number; mae_milli: number | null; abs_error_sum: number; covered: number; coverage_bp: number | null }
export type PredictBody = { kind: string; subject_ref: string; features: Record<string, string | number | boolean> }

export type Assignment = {
  id: string; request_ref: string; candidate_id: string; status: string; score: number; distance_m: number
  offered_at: string; expires_at: string; decided_at: string | null; decided_by: string | null
}
type Candidate = { id: string; lat_micro?: number; lng_micro?: number; load?: number; rating_milli?: number }
export type RankBody = { point: Point; candidates: Candidate[] }
export type AssignBody = RankBody & { request_ref: string }
export type BatchBody = { requests: { request_ref: string; point: Point }[]; candidates: Candidate[]; commit: boolean }
export type RankResult = {
  items: { candidate_id: string; score: number; distance_m: number; parts: { distance: number; load: number; rating: number } }[]
  excluded: { candidate_id: string; reason: string }[]
}
export type BatchResult = {
  pairs: { request_ref: string; candidate_id: string; score: number; distance_m: number }[]
  unassigned: string[]; skipped: string[]; total_score: number; solver: string; assignments: Assignment[]
}

export const agentRunPath = (agent: string) => `/ai/agents/${segment(agent)}/runs` as const
export type AgentRun = {
  id: string; agent: string; goal: string; mode: string; effective_autonomy: string
  status: string; error_code: string | null; call_id: string | null; started_by: string | null
  created_at: string; proposals: AgentProposal[]
}
export type Outcome = 'success' | 'failure' | 'neutral'
export type AgentProposal = {
  id: string; run_id: string; agent: string; action: string; kind: string; risk: string
  args: Record<string, unknown>; allowed_autonomy: string; status: string; reason: string | null
  result: Record<string, unknown> | null; error_code: string | null; executed_by: string | null
  decided_by: string | null; decided_at: string | null; note: string | null; handoff_role: string | null
  outcome: Outcome | null; outcome_by: string | null; outcome_at: string | null; created_at: string
}
export type AgentStats = {
  agents: { agent: string; runs: number; proposals: number; executed: number; rejected: number; pending: number
    outcome_success: number; outcome_failure: number; outcome_neutral: number; success_rate_bp: number | null }[]
}
export type AgentRegistry = {
  agents: { name: string; stage: string; autonomy: string; actions: string[]; max_actions_per_run: number; require_eval: string | null; eval_ready: boolean | null }[]
  actions: { name: string; kind: string; description: string; risk: string; max_autonomy: string; entity: string | null; fields: string[] }[]
}
