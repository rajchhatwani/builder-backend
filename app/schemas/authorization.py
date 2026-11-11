"""Pydantic schemas for a project's authorization settings (builder API layer).

Shapes and sizes are checked here; whether the policies are *legal* (known entities, attributes,
roles, comparable types) is `validation.validate`'s job, so the dashboard can save work in
progress and read every problem in one report.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.authz_engine import MAX_POLICIES
from app.core.enums import AuthorizationModel


class PolicyBody(BaseModel):
    id: str = Field(max_length=60)
    description: str = Field(default="", max_length=600)
    effect: str = Field(max_length=8)
    actions: list[str] = Field(default_factory=list, max_length=200)
    when: dict[str, Any] | None = None


class FieldAccessBody(BaseModel):
    entity: str = Field(max_length=100)
    field: str = Field(max_length=100)
    read_roles: list[str] | None = Field(default=None, max_length=100)
    write_roles: list[str] | None = Field(default=None, max_length=100)


class AuthorizationWrite(BaseModel):
    """Body of PUT /projects/{id}/authorization (replaces the whole block)."""

    model: AuthorizationModel = AuthorizationModel.rbac
    policies: list[PolicyBody] = Field(default_factory=list, max_length=MAX_POLICIES + 50)
    attachments: dict[str, list[str]] = Field(default_factory=dict, max_length=200)
    field_access: list[FieldAccessBody] = Field(default_factory=list, max_length=1000)
    # Optimistic concurrency: when set, the save fails with 409 if someone saved in between.
    expected_version: int | None = Field(default=None, ge=0)
    # Required when the new block gives some role more access than the saved one (else 409).
    confirm_weakening: bool = False


class AuthorizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: uuid.UUID
    model: AuthorizationModel
    policies: list[PolicyBody]
    attachments: dict[str, list[str]]
    field_access: list[FieldAccessBody] = Field(default_factory=list)
    version: int  # 0 = nothing saved yet (the project uses rbac)
    updated_at: datetime | None = None


class AuthorizationIssues(BaseModel):
    issues: list[dict[str, Any]]


class SimulateRequest(BaseModel):
    entity: str = Field(max_length=100)
    op: str = Field(max_length=20)
    subject: dict[str, Any] = Field(default_factory=dict)
    resource: dict[str, Any] | None = None
    env: dict[str, Any] = Field(default_factory=dict)


class SimulateResponse(BaseModel):
    allowed: bool
    reason: str
    allow_matched: list[str]
    deny_matched: list[str]
    trace: list[dict[str, Any]]


class CoverageResponse(BaseModel):
    model: AuthorizationModel
    rows: list[dict[str, Any]]


class RecommendRequest(BaseModel):
    """Answers to the wizard. Every field has a neutral default so a partial form still works."""

    roles: int = Field(default=2, ge=0, le=100)
    ownership_rules: bool = False  # "people edit only their own records"
    tenant_rules: bool = False  # separate organisations share one deployment
    time_or_network_rules: bool = False  # office hours, IP allow-lists
    per_record_rules: bool = False  # rules that depend on a record's status, amount, owner...
    deny_rules: bool = False  # "nobody may X, whatever else says yes"
    audit_needs: bool = False  # reviewers want to read the rules in plain language
    policy_editors: str = Field(default="developers", pattern="^(developers|admins)$")
    public_routes: bool = False  # some routes must work while signed out


class RecommendResponse(BaseModel):
    model: AuthorizationModel
    scores: dict[str, int]
    reasons: list[str]
    cautions: list[str]
    alternatives: list[str]


class AccessPermissionBody(BaseModel):
    """One (entity, operation) slot of the object/row layers, by entity NAME (like the spec)."""

    entity: str = Field(max_length=100)
    operation: str = Field(max_length=20)
    roles: list[str] = Field(default_factory=list, max_length=100)
    row_rule: str | None = Field(default=None, max_length=20)
    custom_filter_field: str | None = Field(default=None, max_length=100)
    custom_filter_value: str | None = Field(default=None, max_length=500)


class AccessDiffRequest(BaseModel):
    """A proposed change to the access rules. A key left out (null) keeps the saved value; a list
    (even an empty one) REPLACES the saved list of that layer."""

    permissions: list[AccessPermissionBody] | None = Field(default=None, max_length=1000)
    field_access: list[FieldAccessBody] | None = Field(default=None, max_length=1000)


class AccessCell(BaseModel):
    layer: str
    entity: str
    target: str
    role: str
    value: str


class AccessMatrixResponse(BaseModel):
    roles: list[str]
    entities: list[str]
    cells: list[AccessCell]


class AccessChange(BaseModel):
    layer: str
    entity: str
    target: str
    role: str
    before: str | None
    after: str | None
    effect: str  # gain | lose | change | added | removed


class AccessDiffResponse(BaseModel):
    changes: list[AccessChange]
    roles_gaining: dict[str, list[str]]
    roles_losing: dict[str, list[str]]
    weakens: bool  # true = some role gains access: applying needs an explicit confirmation
    counts: dict[str, int]
    renames: list[dict[str, str]] = []  # kind | entity | before | after: a rename, not removal+addition
    unprotected_entities: list[str] = []  # added entities with no permission slot (public while sign-in is on)
