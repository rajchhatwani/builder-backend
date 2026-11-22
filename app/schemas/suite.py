"""Schemas for the suite identity routes (path b: join an existing suite)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SuiteMigrationWrite(BaseModel):
    """The next state of the migration. The dual window is two explicit instants (the spec must
    stay deterministic): no default is taken from the clock."""

    model_config = ConfigDict(extra="forbid")

    state: str = Field(pattern=r"^(legacy_read_only|dual|hub_only)$")
    legacy_issuer: str = Field(min_length=1, max_length=512)
    dual_until: datetime | None = None
    window_started_at: datetime | None = None

    @model_validator(mode="after")
    def _window(self) -> "SuiteMigrationWrite":
        from app.core.spec_models import SpecSuiteMigration
        from app.core.suite_migration import window_problems

        problems = window_problems(SpecSuiteMigration(**self.model_dump()))
        if problems:
            field_name, _code, message = problems[0]
            raise ValueError(f"{field_name}: {message}")
        return self


class SuiteMigrationRead(BaseModel):
    suite_id: str
    join_state: str
    state: str
    legacy_issuer: str
    dual_until: datetime | None
    window_started_at: datetime | None


class SuiteJoinImpact(BaseModel):
    current_provider: str
    suite_id: str | None
    migration: dict[str, Any] | None
    realm: str | None
    client_id: str
    hub_url: str | None
    roles_to_client_roles: list[dict[str, str]]
    tenants_to_organisations: bool
    claims_sub_readers: list[dict[str, Any]]
    hooks_scanned: bool
    blockers: list[dict[str, str]]
    warnings: list[dict[str, str]]
    steps: list[dict[str, Any]]
    commands: list[str]
