/** The parts of the project spec (GET /projects/{id}/spec) that the Connect and Operate pages read.
 *  Mirrors app/core/spec_models.py (SpecWebhooks, SpecProviders, SpecJobs, SpecWorkflows). Every field is optional
 *  on the client: an older or partial spec must render, never throw. */
export interface SpecWebhookInbound { name: string; tolerance_seconds?: number; max_body_bytes?: number; dedupe_days?: number }
export interface SpecWebhooks {
  enabled?: boolean
  admin_role?: string
  events?: string[]
  max_consecutive_failures?: number
  secret_overlap_hours?: number
  timeout_seconds?: number
  max_payload_bytes?: number
  allow_http?: boolean
  allowed_ports?: number[]
  inbound?: SpecWebhookInbound[]
}
export interface SpecProviderAdapter { kind: string; name: string; settings?: Record<string, string | number | boolean> }
export interface SpecProviders {
  enabled?: boolean
  admin_role?: string
  adapters?: SpecProviderAdapter[]
  timeout_seconds?: number
  max_attempts?: number
  breaker_failures?: number
  breaker_reset_seconds?: number
}
export interface SpecJobRetry { max_attempts?: number; backoff_seconds?: number; backoff?: string }
export interface SpecJob { name: string; queue?: string; handler: string; retry?: SpecJobRetry; timeout_seconds?: number }
export interface SpecJobSchedule { name: string; job: string; cron: string; timezone?: string; enabled?: boolean; missed?: string }
export interface SpecWorkerGroup { name: string; concurrency?: number; queues?: string[]; placement?: string }
export interface SpecJobs {
  enabled?: boolean
  queue?: { backend?: string }
  worker_groups?: SpecWorkerGroup[]
  jobs?: SpecJob[]
  schedules?: SpecJobSchedule[]
}
export interface SpecWorkflowStep { name: string; kind?: string; job?: string | null; compensate?: boolean; timeout_seconds?: number; retry?: SpecJobRetry }
export interface SpecWorkflow { name: string; steps?: SpecWorkflowStep[]; roles?: string[]; on_failure?: string; timeout_seconds?: number }
export interface SpecWorkflows {
  enabled?: boolean
  runtime?: string
  worker?: { concurrency?: number }
  workflows?: SpecWorkflow[]
}
export interface SpecBlocks {
  webhooks?: SpecWebhooks | null
  providers?: SpecProviders | null
  jobs?: SpecJobs | null
  workflows?: SpecWorkflows | null
}
