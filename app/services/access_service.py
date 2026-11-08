"""Who is calling, and what may they do to which project. Used by the request guard."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import platform_security as sec
from app.models.auth_custom_field import AuthCustomField
from app.models.entity import Entity
from app.models.enums import AccountStatus, MemberRole, PlatformRole, TokenAudience
from app.models.field import Field
from app.models.generation import Generation
from app.models.platform import (
    ApiToken,
    ImpersonationSession,
    Organization,
    OrganizationMember,
    PlatformUser,
    ProjectMember,
)
from app.models.project_permission import ProjectPermission
from app.models.project_role import ProjectRole
from app.models.relation import Relation

ROLE_LEVEL = {MemberRole.viewer: 1, MemberRole.editor: 2, MemberRole.owner: 3}
_LAST_USED_RESOLUTION = timedelta(minutes=1)  # do not write on every API-token request


@dataclass(frozen=True)
class ImpersonationInfo:
    """An operator "viewing as" a member (§4.5). Read from the session row on every request."""

    session_id: uuid.UUID
    operator_id: uuid.UUID
    operator_email: str
    operator_name: str
    organization_id: uuid.UUID
    organization_slug: str
    organization_name: str
    expires_at: datetime
    writes_until: datetime | None

    def writes_allowed(self, now: datetime | None = None) -> bool:
        return self.writes_until is not None and self.writes_until > (now or _now())


@dataclass(frozen=True)
class Principal:
    user: PlatformUser
    via: str  # "session" (JWT) or "api_token"
    audience: TokenAudience
    scopes: frozenset[str]  # empty for sessions: they are not scope-limited
    token_project_id: uuid.UUID | None = None  # an API token pinned to one project
    # How the session was signed in (`amr` claim): {'pwd'}, {'pwd', 'otp'}, {'sso'}, ...
    # Empty for API tokens.
    auth_methods: frozenset[str] = frozenset()
    # Set when an operator is viewing as this user: `via` is then "impersonation".
    impersonation: ImpersonationInfo | None = None

    @property
    def mfa_satisfied(self) -> bool:
        """For an org that requires MFA (§4.4): a session must have used a second factor (or
        SSO, where the IdP owns MFA); an API token's owner must have MFA set up or be an
        SSO-only account."""
        if self.via in ("session", "impersonation"):
            return bool(self.auth_methods & sec.MFA_METHODS)
        return self.user.mfa_enabled or self.user.password_hash == sec.SSO_ONLY_PASSWORD_HASH


def _now() -> datetime:
    return datetime.now(UTC)


async def principal_from_jwt(
    db: AsyncSession, token: str, audience: TokenAudience
) -> Principal | None:
    """None for anything wrong with the token or the account behind it."""
    try:
        claims = sec.decode_jwt(
            token,
            audience=sec.AUDIENCE_ADMIN if audience is TokenAudience.admin else sec.AUDIENCE_APP,
        )
        user_id = uuid.UUID(claims["sub"])
    except (sec.TokenError, ValueError):
        return None
    user = await db.get(PlatformUser, user_id)
    if (
        user is None
        or user.status is not AccountStatus.active
        or claims.get("tv") != user.token_version
    ):
        return None
    amr = claims.get("amr")
    methods = frozenset(m for m in amr if isinstance(m, str)) if isinstance(amr, list) else None
    if "imp_sid" in claims:
        # A "view as" token: only ever a customer-surface token, and only while its session
        # row, the operator, the member and the org's consent all still hold.
        if audience is not TokenAudience.app:
            return None
        info = await _impersonation_info(db, claims, user)
        if info is None:
            return None
        return Principal(
            user,
            "impersonation",
            audience,
            frozenset(),
            auth_methods=methods or frozenset(),
            impersonation=info,
        )
    return Principal(user, "session", audience, frozenset(), auth_methods=methods or frozenset())


async def _impersonation_info(
    db: AsyncSession, claims: dict[str, object], target: PlatformUser
) -> ImpersonationInfo | None:
    try:
        session_id = uuid.UUID(str(claims["imp_sid"]))
    except ValueError:
        return None
    row = await db.get(ImpersonationSession, session_id)
    now = _now()
    if (
        row is None
        or row.ended_at is not None
        or row.expires_at <= now
        or row.target_user_id != target.id
        or str(claims.get("imp_by")) != str(row.operator_id)
    ):
        return None
    operator = await db.get(PlatformUser, row.operator_id)
    if (
        operator is None
        or operator.status is not AccountStatus.active
        or operator.platform_role is not PlatformRole.platform_admin
    ):
        return None
    org = await db.get(Organization, row.organization_id)
    if (
        org is None
        or not org.allow_impersonation
        or await db.get(OrganizationMember, (org.id, target.id)) is None
    ):
        return None
    return ImpersonationInfo(
        session_id=row.id,
        operator_id=operator.id,
        operator_email=operator.email,
        operator_name=operator.name,
        organization_id=org.id,
        organization_slug=org.slug,
        organization_name=org.name,
        expires_at=row.expires_at,
        writes_until=row.writes_until,
    )


async def principal_from_api_token(db: AsyncSession, token: str) -> Principal | None:
    public_id = sec.parse_api_token(token)
    if public_id is None:
        return None
    row = (
        await db.execute(select(ApiToken).where(ApiToken.public_id == public_id))
    ).scalar_one_or_none()
    now = _now()
    if (
        row is None
        or not sec.tokens_equal(row.token_hash, sec.hash_token(token))
        or row.revoked_at is not None
        or row.expires_at <= now
    ):
        return None
    user = await db.get(PlatformUser, row.user_id)
    if user is None or user.status is not AccountStatus.active:
        return None
    if row.last_used_at is None or now - row.last_used_at > _LAST_USED_RESOLUTION:
        row.last_used_at = now
        await db.commit()
    return Principal(user, "api_token", TokenAudience.app, frozenset(row.scopes), row.project_id)


async def member_role(
    db: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID
) -> MemberRole | None:
    return (
        await db.execute(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
            )
        )
    ).scalar_one_or_none()


# Route template prefix + path parameter -> how to find the owning project.
async def project_of(db: AsyncSession, template: str, params: dict[str, str]) -> uuid.UUID | None:
    """The project a request is about, or None when the route is not about one (or the id is bad).

    Every route of the builder must resolve here or be listed as unscoped in the guard; a new route
    that does neither is refused, and a test walks the OpenAPI schema to catch it before release.
    """
    try:
        if "project_id" in params:
            return uuid.UUID(params["project_id"])
        if "entity_id" in params:
            return await _scalar(db, Entity.project_id, Entity.id == uuid.UUID(params["entity_id"]))
        if "field_id" in params:
            fid = uuid.UUID(params["field_id"])
            if template.startswith("/auth/custom-fields/"):
                return await _scalar(db, AuthCustomField.project_id, AuthCustomField.id == fid)
            return await _scalar(
                db,
                Entity.project_id,
                Entity.id == Field.entity_id,
                Field.id == fid,
            )
        if "relation_id" in params:
            return await _scalar(
                db, Relation.project_id, Relation.id == uuid.UUID(params["relation_id"])
            )
        if "role_id" in params:
            return await _scalar(
                db, ProjectRole.project_id, ProjectRole.id == uuid.UUID(params["role_id"])
            )
        if "permission_id" in params:
            return await _scalar(
                db,
                ProjectPermission.project_id,
                ProjectPermission.id == uuid.UUID(params["permission_id"]),
            )
        if "generation_id" in params:
            return await _scalar(
                db, Generation.project_id, Generation.id == uuid.UUID(params["generation_id"])
            )
    except ValueError:
        return None
    return None


async def _scalar(db: AsyncSession, column: object, *conditions: object) -> uuid.UUID | None:
    return (await db.execute(select(column).where(*conditions))).scalar_one_or_none()  # type: ignore[call-overload]
