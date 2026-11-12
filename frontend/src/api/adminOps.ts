/** Admin operations + admin usage-limit types (CP-5V backend contract). */
import type { OrgUsageSummary } from './types'

export interface OpsJob {
  job: string
  interval_seconds: number | null
  last_run_at: string | null
  last_status: 'ok' | 'failed' | null
  last_error: string | null
  runs: number
  next_expected_at: string | null
  stale: boolean
}
export type GoliveStatus = 'pass' | 'fail' | 'warn' | 'skipped'
export interface GoliveReport {
  ran_at: string
  ok: boolean
  passed: number
  failed: number
  warnings: number
  skipped: number
  checks: { check: string; status: GoliveStatus; detail: string }[]
}
export interface OpsOverview {
  generated_at: string
  scheduler: { jobs: OpsJob[] }
  idle_workspaces: { ttl_days: number; live_workspaces: number; idle_past_ttl: number }
  reports: { enabled_schedules: number; disabled_schedules: number; last_run_at: string | null; next_run_at: string | null }
  usage_defaults: { metric: string; unit: string; period: 'day' | 'month' | 'none'; default_limit: number | null }[]
  key_provider: { kind: 'env' | 'file' | 'command'; healthy: boolean; active_key_id: string | null; key_count: number; error: string | null }
  golive: GoliveReport
}
export type AdminUsageSummary = OrgUsageSummary
