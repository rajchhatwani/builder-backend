"""Request/response schemas for the SCIM setup page (Phase E). The SCIM protocol itself
(`/scim/v2`) speaks `application/scim+json`, built in `app.services.scim_protocol`."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ScimGroupSummary(BaseModel):
    display_name: str
    members: int
    mapped_role: str | None = None


class ScimConfigRead(BaseModel):
    configured: bool
    allowed_by_plan: bool
    active: bool = False
    # What the org admin pastes into the IdP: the SCIM base URL (Users endpoint = base + /Users).
    base_url: str
    users_url: str
    token_hint: str | None = None  # last 4 characters, e.g. "…a1B2"; never the token
    token_created_at: datetime | None = None
    created_at: datetime | None = None
    last_sync_at: datetime | None = None
    # §12.E.3: group display name (lower-cased) -> org role.
    group_roles: dict[str, str] = Field(default_factory=dict)
    active_users: int = 0
    deactivated_users: int = 0
    groups: list[ScimGroupSummary] = Field(default_factory=list)


class ScimTokenRead(ScimConfigRead):
    """POST /orgs/{slug}/scim/token. `token` is shown this once; only its hash is kept."""

    token: str


class ScimConfigUpdate(BaseModel):
    active: bool | None = None
    group_roles: dict[str, Literal["owner", "admin", "member"]] | None = None
