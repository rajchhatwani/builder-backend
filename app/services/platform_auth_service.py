"""Accounts and sessions of the builder itself. Framework-free: raises AppError, takes plain data.

Security behaviour worth knowing (each one has a test):
  - Login failures are indistinguishable: unknown e-mail, wrong password, suspended account and a
    locked account all answer the same 401 and all cost one password hash.
  - After `login_max_failures` wrong passwords the account is locked for `lockout_minutes`.
  - Refresh tokens rotate on every use. Presenting an already-used one (outside a short grace for
    two tabs racing) revokes the whole login family and every access token of that person.
  - Changing a password or suspending an account bumps `token_version`, which kills access tokens
    immediately instead of at their natural expiry.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import platform_security as sec
from app.exceptions import AppError
from app.models.enums import (
    AccountStatus,
    AuditResult,
    MemberRole,
    PlatformRole,
    TokenAudience,
)
from app.models.platform import PlatformUser, ProjectMember, RefreshToken
from app.models.project import Project
from app.services import audit_service

_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+$")
# Two browser tabs refreshing at once present the same token; the loser is refused, not punished.
REUSE_GRACE = timedelta(seconds=10)


def _now() -> datetime:
    return datetime.now(UTC)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def invalid_credentials() -> AppError:
    return AppError(
        code="invalid_credentials", message="invalid e-mail or password", status_code=401
    )


def invalid_session() -> AppError:
    return AppError(
        code="invalid_session", message="the session is no longer valid", status_code=401
    )


@dataclass(frozen=True)
class RequestInfo:
    """What the services need to know about the caller's request, for audit and sessions."""

    client_ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class Session:
    access_token: str
    refresh_token: str
    expires_in: int
    refresh_max_age: int
    user: PlatformUser


class PlatformAuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.db = session
        self.settings = settings

    # -- accounts ------------------------------------------------------------------------

    async def register(
        self, *, email: str, password: str, name: str, info: RequestInfo
    ) -> PlatformUser:
        if self.settings.signup_mode != "open":
            raise AppError(
                code="signup_closed",
                message="sign-up is closed; ask an administrator",
                status_code=403,
            )
        user = await self.create_user(
            email=email, password=password, name=name, role=PlatformRole.customer, info=info
        )
        await audit_service.record(
            self.db,
            action="account.register",
            actor_id=user.id,
            actor_email=user.email,
            target_type="user",
            target_id=user.id,
            client_ip=info.client_ip,
            request_id=info.request_id,
        )
        await self.db.commit()
        return user

    async def create_user(
        self,
        *,
        email: str,
        password: str,
        name: str,
        role: PlatformRole,
        info: RequestInfo,
        must_change_password: bool = False,
    ) -> PlatformUser:
        """Validate and insert (flush, no commit). Used by sign-up, admin creation, bootstrap."""
        email = normalize_email(email)
        if not _EMAIL_RE.match(email) or len(email) > 254:
            raise AppError(
                code="invalid_email", message="not a valid e-mail address", status_code=422
            )
        problems = sec.password_problems(password, email)
        if problems:
            raise AppError(
                code="weak_password",
                message="password " + "; ".join(problems),
                status_code=422,
            )
        user = PlatformUser(
            email=email,
            name=name.strip()[:100],
            password_hash=sec.hash_password(password),
            platform_role=role,
            must_change_password=must_change_password,
        )
        self.db.add(user)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            raise AppError(
                code="conflict",
                message="an account with this e-mail already exists",
                status_code=409,
            ) from exc
        return user

    # -- login ---------------------------------------------------------------------------

    async def login(
        self, *, email: str, password: str, audience: TokenAudience, info: RequestInfo
    ) -> Session:
        email = normalize_email(email)
        user = (
            await self.db.execute(select(PlatformUser).where(PlatformUser.email == email))
        ).scalar_one_or_none()
        now = _now()
        if user is None:
            sec.burn_password_check(password)
            await self._login_failed(None, email, info, "unknown_account")
            raise invalid_credentials()
        locked = user.locked_until is not None and user.locked_until > now
        password_ok = sec.verify_password(password, user.password_hash)  # always spend the time
        admin_only = audience is TokenAudience.admin and user.platform_role is PlatformRole.customer
        if locked or not password_ok or user.status is not AccountStatus.active or admin_only:
            reason = (
                "locked"
                if locked
                else "bad_password"
                if not password_ok
                else "suspended"
                if user.status is not AccountStatus.active
                else "not_admin"
            )
            if not password_ok and not locked:
                user.failed_logins += 1
                if user.failed_logins >= self.settings.login_max_failures:
                    user.locked_until = now + timedelta(minutes=self.settings.lockout_minutes)
                    user.failed_logins = 0
                    reason = "locked_now"
            await self._login_failed(user, email, info, reason)
            raise invalid_credentials()
        user.failed_logins = 0
        user.locked_until = None
        user.last_login_at = now
        session = await self._start_session(user, audience, info, family_id=uuid.uuid4())
        await audit_service.record(
            self.db,
            action="admin.login" if audience is TokenAudience.admin else "account.login",
            actor_id=user.id,
            actor_email=user.email,
            target_type="user",
            target_id=user.id,
            client_ip=info.client_ip,
            request_id=info.request_id,
        )
        await self.db.commit()
        return session

    async def _login_failed(
        self, user: PlatformUser | None, email: str, info: RequestInfo, reason: str
    ) -> None:
        await audit_service.record(
            self.db,
            action="account.login_failed",
            result=AuditResult.denied,
            actor_id=user.id if user else None,
            # The attempted address is kept (useful for spotting a spray); the password never is.
            actor_email=email[:254],
            client_ip=info.client_ip,
            request_id=info.request_id,
            detail={"reason": reason},
        )
        await self.db.commit()

    async def _start_session(
        self,
        user: PlatformUser,
        audience: TokenAudience,
        info: RequestInfo,
        *,
        family_id: uuid.UUID,
    ) -> Session:
        s = self.settings
        refresh_ttl = (
            timedelta(hours=s.admin_refresh_token_hours)
            if audience is TokenAudience.admin
            else timedelta(days=s.refresh_token_days)
        )
        raw, digest = sec.new_refresh_token()
        self.db.add(
            RefreshToken(
                user_id=user.id,
                family_id=family_id,
                audience=audience,
                token_hash=digest,
                expires_at=_now() + refresh_ttl,
                client_ip=info.client_ip,
                user_agent=(info.user_agent or "")[:200] or None,
            )
        )
        ttl = s.access_token_minutes * 60
        access = sec.encode_jwt(
            sec.access_claims(
                user_id=str(user.id),
                audience=sec.AUDIENCE_ADMIN
                if audience is TokenAudience.admin
                else sec.AUDIENCE_APP,
                token_version=user.token_version,
                ttl_seconds=ttl,
            )
        )
        return Session(access, raw, ttl, int(refresh_ttl.total_seconds()), user)

    # -- refresh / logout ----------------------------------------------------------------

    async def refresh(
        self, *, refresh_token: str, audience: TokenAudience, info: RequestInfo
    ) -> Session:
        row = (
            await self.db.execute(
                select(RefreshToken).where(RefreshToken.token_hash == sec.hash_token(refresh_token))
            )
        ).scalar_one_or_none()
        now = _now()
        if row is None or row.audience is not audience:
            raise invalid_session()
        user = await self.db.get(PlatformUser, row.user_id)
        if (
            user is None
            or user.status is not AccountStatus.active
            or row.revoked_at is not None
            or row.expires_at <= now
        ):
            raise invalid_session()
        if audience is TokenAudience.admin and user.platform_role is PlatformRole.customer:
            raise invalid_session()
        # Claim the token atomically: of two racing requests exactly one gets the row back.
        claimed = (
            await self.db.execute(
                update(RefreshToken)
                .where(RefreshToken.id == row.id, RefreshToken.used_at.is_(None))
                .values(used_at=now)
                .returning(RefreshToken.id)
            )
        ).first()
        if claimed is None:
            await self.db.refresh(row)
            if row.used_at is not None and now - row.used_at <= REUSE_GRACE:
                raise invalid_session()  # two tabs racing: refuse the loser, keep the session
            await self._revoke_family(row.family_id, user, info, "refresh_reuse")
            raise invalid_session()
        session = await self._start_session(user, audience, info, family_id=row.family_id)
        await self.db.commit()
        return session

    async def _revoke_family(
        self, family_id: uuid.UUID, user: PlatformUser, info: RequestInfo, why: str
    ) -> None:
        await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=_now())
        )
        user.token_version += 1  # a stolen access token dies with the family
        await audit_service.record(
            self.db,
            action="account.session_revoked",
            result=AuditResult.denied if why == "refresh_reuse" else AuditResult.ok,
            actor_id=user.id,
            actor_email=user.email,
            target_type="user",
            target_id=user.id,
            client_ip=info.client_ip,
            request_id=info.request_id,
            detail={"reason": why},
        )
        await self.db.commit()

    async def logout(self, *, refresh_token: str, info: RequestInfo) -> None:
        """Revoke the login family the token belongs to. Unknown tokens are ignored silently."""
        row = (
            await self.db.execute(
                select(RefreshToken).where(RefreshToken.token_hash == sec.hash_token(refresh_token))
            )
        ).scalar_one_or_none()
        if row is None:
            return
        user = await self.db.get(PlatformUser, row.user_id)
        if user is None:
            return
        await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=_now())
        )
        await audit_service.record(
            self.db,
            action="account.logout",
            actor_id=user.id,
            actor_email=user.email,
            client_ip=info.client_ip,
            request_id=info.request_id,
        )
        await self.db.commit()

    async def revoke_all_sessions(self, user: PlatformUser) -> None:
        """Sign a person out everywhere (no commit)."""
        await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=_now())
        )
        user.token_version += 1

    # -- password ------------------------------------------------------------------------

    async def change_password(
        self,
        user: PlatformUser,
        *,
        current_password: str,
        new_password: str,
        audience: TokenAudience,
        info: RequestInfo,
    ) -> Session:
        if not sec.verify_password(current_password, user.password_hash):
            await audit_service.record(
                self.db,
                action="account.password_change",
                result=AuditResult.denied,
                actor_id=user.id,
                actor_email=user.email,
                client_ip=info.client_ip,
                request_id=info.request_id,
                detail={"reason": "wrong_current_password"},
            )
            await self.db.commit()
            raise AppError(
                code="invalid_credentials", message="current password is wrong", status_code=403
            )
        problems = sec.password_problems(new_password, user.email)
        if problems:
            raise AppError(
                code="weak_password", message="password " + "; ".join(problems), status_code=422
            )
        if sec.verify_password(new_password, user.password_hash):
            raise AppError(
                code="weak_password",
                message="the new password must differ from the current one",
                status_code=422,
            )
        user.password_hash = sec.hash_password(new_password)
        user.password_changed_at = _now()
        user.must_change_password = False
        await self.revoke_all_sessions(user)  # every other device signs out
        session = await self._start_session(user, audience, info, family_id=uuid.uuid4())
        await audit_service.record(
            self.db,
            action="account.password_change",
            actor_id=user.id,
            actor_email=user.email,
            target_type="user",
            target_id=user.id,
            client_ip=info.client_ip,
            request_id=info.request_id,
        )
        await self.db.commit()
        return session

    # -- bootstrap -----------------------------------------------------------------------

    async def adopt_unclaimed_projects(self, user: PlatformUser) -> int:
        """Make `user` the owner of every project that has no members (pre-accounts data)."""
        unclaimed = (
            await self.db.execute(
                select(Project.id).where(
                    ~select(ProjectMember.project_id)
                    .where(ProjectMember.project_id == Project.id)
                    .exists()
                )
            )
        ).scalars()
        adopted = 0
        for project_id in unclaimed:
            self.db.add(
                ProjectMember(project_id=project_id, user_id=user.id, role=MemberRole.owner)
            )
            adopted += 1
        return adopted

    async def bootstrap_admin(self) -> PlatformUser | None:
        """Create the first administrator from the environment and adopt unclaimed projects.

        Runs at every startup and is idempotent: it does nothing once any administrator exists.
        Projects created before accounts existed have no members; they become the bootstrap
        administrator's, so no data is lost and no customer can see them.
        """
        s = self.settings
        password = (
            s.bootstrap_admin_password.get_secret_value() if s.bootstrap_admin_password else ""
        )
        if not s.bootstrap_admin_email or not password:
            return None
        existing = (
            await self.db.execute(
                select(func.count())
                .select_from(PlatformUser)
                .where(PlatformUser.platform_role == PlatformRole.platform_admin)
            )
        ).scalar_one()
        if existing:
            return None
        admin = await self.create_user(
            email=s.bootstrap_admin_email,
            password=password,
            name="Administrator",
            role=PlatformRole.platform_admin,
            info=RequestInfo(),
        )
        adopted = await self.adopt_unclaimed_projects(admin)
        await audit_service.record(
            self.db,
            action="admin.bootstrap",
            actor_id=admin.id,
            actor_email=admin.email,
            target_type="user",
            target_id=admin.id,
            detail={"adopted_projects": adopted},
        )
        await self.db.commit()
        return admin
