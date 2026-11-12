from datetime import datetime

from pydantic import BaseModel


class JobStatusRead(BaseModel):
    job: str
    interval_seconds: int | None
    last_run_at: datetime | None
    last_status: str | None  # ok | failed | null (never ran)
    last_error: str | None  # exception type only
    runs: int
    next_expected_at: datetime | None
    stale: bool


class SchedulerRead(BaseModel):
    jobs: list[JobStatusRead]


class IdleWorkspacesRead(BaseModel):
    ttl_days: int
    live_workspaces: int
    idle_past_ttl: int


class ReportsStatusRead(BaseModel):
    enabled_schedules: int
    disabled_schedules: int
    last_run_at: datetime | None
    next_run_at: datetime | None


class UsageDefaultRead(BaseModel):
    metric: str
    unit: str
    period: str
    default_limit: int | None


class KeyProviderRead(BaseModel):
    kind: str
    healthy: bool
    active_key_id: str | None
    key_count: int
    error: str | None


class GoliveCheckRead(BaseModel):
    check: str
    status: str  # pass | fail | warn | skipped
    detail: str


class GoliveRead(BaseModel):
    ran_at: datetime
    ok: bool  # no failed check
    passed: int
    failed: int
    warnings: int
    skipped: int
    checks: list[GoliveCheckRead]


class OperationsRead(BaseModel):
    generated_at: datetime
    scheduler: SchedulerRead
    idle_workspaces: IdleWorkspacesRead
    reports: ReportsStatusRead
    usage_defaults: list[UsageDefaultRead]
    key_provider: KeyProviderRead
    golive: GoliveRead
