"""Built-in TOTP MFA for every account (PLATFORM_SAAS_PLAN §4.4 Phase 1).

  - Setting up stores an encrypted secret; it only counts once a code proves the authenticator
    works (`enable`). Ten one-time recovery codes are shown once and stored as SHA-256.
  - Sign-in: a correct password answers an MFA challenge (a short-lived token bound to the
    account's `token_version`, the audience it is for and its purpose). The code is checked
    here. Wrong codes count towards the same lockout as wrong passwords.
  - Platform staff always need TOTP (`admin_mfa_required`): without it their password answers
    an *enrolment* challenge, which can set up TOTP but never sign in by itself.
  - Org MFA policy (`organizations.require_mfa`) is checked per request (`api.security`); here
    it only stops a member from switching MFA off while an org needs it.
Secrets, codes and challenge tokens are never logged or audited.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import crypto, totp
from app.core import platform_security as sec
from app.exceptions import AppError
from app.models.enums import AccountStatus, AuditResult, TokenAudience
from app.models.platform import MfaRecoveryCode, Organization, OrganizationMember, PlatformUser
from app.services import audit_service
from app.services.platform_auth_service import (
    MFA_ENROLL,
    MFA_VERIFY,
    PlatformAuthService,
    RequestInfo,
    Session,
    invalid_credentials,
    is_staff,
)


def _now() -> datetime:
    return datetime.now(UTC)


def invalid_mfa_token() -> AppError:
    return AppError(
        code="invalid_mfa_token",
        message="this sign-in step has expired or is not valid; sign in again",
        status_code=401,
    )


def invalid_code(status_code: int) -> AppError:
    return AppError(
        code="invalid_mfa_code", message="that code is not valid", status_code=status_code
    )


def _conflict(code: str, message: str, details: list[dict[str, object]] | None = None) -> AppError:
    return AppError(code=code, message=message, status_code=409, details=details)


@dataclass(frozen=True)
class TotpSetup:
    secret: str
    otpauth_uri: str


@dataclass(frozen=True)
class MfaStatus:
    totp_enabled: bool
    enabled_at: datetime | None
    recovery_codes_left: int
    required_for_staff: bool
    required_by: list[Organization]
    sso_only: bool


class MfaService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.db = session
        self.settings = settings
        self.auth = PlatformAuthService(session, settings)

    # -- helpers ---------------------------------------------------------------------------

    async def _audit(
        self,
        user: PlatformUser,
        info: RequestInfo,
        action: str,
        *,
        result: AuditResult = AuditResult.ok,
        actor: PlatformUser | None = None,
        detail: dict[str, object] | None = None,
    ) -> None:
        who = actor or user
        await audit_service.record(
            self.db,
            action=action,
            result=result,
            actor_id=who.id,
            actor_email=who.email,
            target_type="user",
            target_id=user.id,
            client_ip=info.client_ip,
            request_id=info.request_id,
            detail=detail,
        )

    def _secret(self, user: PlatformUser) -> str | None:
        return crypto.decrypt(user.totp_secret_enc) if user.totp_secret_enc else None

    async def _new_recovery_codes(self, user: PlatformUser) -> list[str]:
        await self.db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))
        codes = totp.new_recovery_codes()
        for code in codes:
            self.db.add(
                MfaRecoveryCode(
                    user_id=user.id, code_hash=sec.hash_token(totp.normalize_recovery_code(code))
                )
            )
        return codes

    async def _check_code(
        self, user: PlatformUser, code: str, *, allow_recovery: bool = True
    ) -> str | None:
        """'otp' or 'rc' when the code is good (and is then spent), else None."""
        secret = self._secret(user)
        if secret is None:
            return None
        step = totp.verify(secret, code, last_step=user.totp_last_step)
        if step is not None:
            user.totp_last_step = step
            return "otp"
        if not allow_recovery:
            return None
        normalized = totp.normalize_recovery_code(code)
        if len(normalized) != 10:
            return None
        used = (
            await self.db.execute(
                update(MfaRecoveryCode)
                .where(
                    MfaRecoveryCode.user_id == user.id,
                    MfaRecoveryCode.code_hash == sec.hash_token(normalized),
                    MfaRecoveryCode.used_at.is_(None),
                )
                .values(used_at=_now())
                .returning(MfaRecoveryCode.id)
            )
        ).first()
        return "rc" if used is not None else None

    async def _code_failed(self, user: PlatformUser, info: RequestInfo, reason: str) -> None:
        """A wrong code counts like a wrong password (§4.4: the lockout covers both factors)."""
        user.failed_logins += 1
        if user.failed_logins >= self.settings.login_max_failures:
            user.locked_until = _now() + timedelta(minutes=self.settings.lockout_minutes)
            user.failed_logins = 0
            reason = "locked_now"
        await audit_service.record(
            self.db,
            action="account.login_failed",
            result=AuditResult.denied,
            actor_id=user.id,
            actor_email=user.email,
            client_ip=info.client_ip,
            request_id=info.request_id,
            detail={"reason": reason},
        )
        await self.db.commit()

    async def _check_signed_in_code(
        self, user: PlatformUser, code: str, info: RequestInfo, *, allow_recovery: bool = True
    ) -> None:
        """A code typed in a signed-in session is limited like one typed at sign-in, so a stolen
        session can't guess its way past the second factor."""
        if user.locked_until is not None and user.locked_until > _now():
            raise AppError(
                code="too_many_attempts",
                message="too many wrong codes; wait a few minutes",
                status_code=429,
            )
        if await self._check_code(user, code, allow_recovery=allow_recovery) is None:
            await self._code_failed(user, info, "bad_otp")
            raise invalid_code(422)

    async def required_by(self, user: PlatformUser) -> list[Organization]:
        return list(
            (
                await self.db.execute(
                    select(Organization)
                    .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
                    .where(
                        OrganizationMember.user_id == user.id,
                        Organization.require_mfa.is_(True),
                        Organization.deleted_at.is_(None),
                    )
                    .order_by(Organization.name)
                )
            )
            .scalars()
            .all()
        )

    async def _codes_left(self, user: PlatformUser) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(MfaRecoveryCode)
                    .where(MfaRecoveryCode.user_id == user.id, MfaRecoveryCode.used_at.is_(None))
                )
            ).scalar_one()
        )

    def _new_secret(self, user: PlatformUser) -> TotpSetup:
        secret = totp.new_secret()
        user.totp_secret_enc = crypto.encrypt(secret)
        user.totp_last_step = None
        return TotpSetup(
            secret, totp.otpauth_uri(secret, account=user.email, issuer=self.settings.totp_issuer)
        )

    async def _enable(self, user: PlatformUser) -> list[str]:
        user.totp_enabled_at = _now()
        return await self._new_recovery_codes(user)

    # -- sign-in (no session yet) ----------------------------------------------------------

    async def _challenge_user(
        self, token: str, audience: TokenAudience, purpose: str
    ) -> PlatformUser:
        try:
            claims = sec.decode_jwt(token, audience=sec.AUDIENCE_MFA)
            user_id = uuid.UUID(claims["sub"])
        except (sec.TokenError, ValueError):
            raise invalid_mfa_token() from None
        if claims.get("for") != audience.value or claims.get("pur") != purpose:
            raise invalid_mfa_token()
        user = await self.db.get(PlatformUser, user_id)
        if (
            user is None
            or user.status is not AccountStatus.active
            or claims.get("tv") != user.token_version
            or (audience is TokenAudience.admin and not is_staff(user))
        ):
            raise invalid_mfa_token()
        if purpose == MFA_ENROLL and user.mfa_enabled:
            raise invalid_mfa_token()  # already enrolled: a password alone can't replace TOTP
        if purpose == MFA_VERIFY and not user.mfa_enabled:
            raise invalid_mfa_token()
        if user.locked_until is not None and user.locked_until > _now():
            raise invalid_credentials()
        return user

    async def verify_login(
        self, *, mfa_token: str, code: str, audience: TokenAudience, info: RequestInfo
    ) -> Session:
        user = await self._challenge_user(mfa_token, audience, MFA_VERIFY)
        method = await self._check_code(user, code)
        if method is None:
            await self._code_failed(user, info, "bad_otp")
            raise invalid_code(401)
        detail: dict[str, object] = {"mfa": "totp" if method == "otp" else "recovery_code"}
        return await self.auth.finish_login(
            user, audience, info, methods=f"pwd {method}", detail=detail
        )

    async def setup_with_challenge(self, *, mfa_token: str, audience: TokenAudience) -> TotpSetup:
        user = await self._challenge_user(mfa_token, audience, MFA_ENROLL)
        setup = self._new_secret(user)
        await self.db.commit()
        return setup

    async def enable_with_challenge(
        self, *, mfa_token: str, code: str, audience: TokenAudience, info: RequestInfo
    ) -> tuple[Session, list[str]]:
        user = await self._challenge_user(mfa_token, audience, MFA_ENROLL)
        if user.totp_secret_enc is None:
            raise _conflict("mfa_setup_required", "set up an authenticator app first")
        if await self._check_code(user, code, allow_recovery=False) is None:
            await self._code_failed(user, info, "bad_otp")
            raise invalid_code(401)
        codes = await self._enable(user)
        await self._audit(user, info, "account.mfa_enabled", detail={"during": "sign_in"})
        session = await self.auth.finish_login(
            user, audience, info, methods="pwd otp", detail={"mfa": "totp", "enrolled": True}
        )
        return session, codes

    # -- signed in -------------------------------------------------------------------------

    async def status(self, user: PlatformUser) -> MfaStatus:
        return MfaStatus(
            totp_enabled=user.mfa_enabled,
            enabled_at=user.totp_enabled_at,
            recovery_codes_left=await self._codes_left(user) if user.mfa_enabled else 0,
            required_for_staff=is_staff(user) and self.settings.admin_mfa_required,
            required_by=await self.required_by(user),
            sso_only=user.password_hash == sec.SSO_ONLY_PASSWORD_HASH,
        )

    def _check_password(self, user: PlatformUser, password: str) -> None:
        if user.password_hash == sec.SSO_ONLY_PASSWORD_HASH:
            raise _conflict(
                "sso_only_account",
                "this account signs in through your organization's SSO; "
                "two-factor authentication is handled there",
            )
        if not sec.verify_password(password, user.password_hash):
            raise AppError(
                code="invalid_password", message="the password is not correct", status_code=422
            )

    async def setup(self, user: PlatformUser, *, password: str) -> TotpSetup:
        if user.mfa_enabled:
            raise _conflict("mfa_already_enabled", "two-factor authentication is already on")
        self._check_password(user, password)
        setup = self._new_secret(user)
        await self.db.commit()
        return setup

    async def enable(
        self, user: PlatformUser, *, code: str, info: RequestInfo
    ) -> tuple[Session, list[str]]:
        if user.mfa_enabled:
            raise _conflict("mfa_already_enabled", "two-factor authentication is already on")
        if user.totp_secret_enc is None:
            raise _conflict("mfa_setup_required", "set up an authenticator app first")
        await self._check_signed_in_code(user, code, info, allow_recovery=False)
        codes = await self._enable(user)
        await self._audit(user, info, "account.mfa_enabled")
        # A fresh login family that counts as MFA'd, so an org requiring MFA works at once.
        session = await self.auth.issue_session(user, info, methods="pwd otp")
        await self.db.commit()
        return session, codes

    async def disable(
        self, user: PlatformUser, *, password: str, code: str, info: RequestInfo
    ) -> None:
        if not user.mfa_enabled:
            raise _conflict("mfa_not_enabled", "two-factor authentication is not on")
        if is_staff(user) and self.settings.admin_mfa_required:
            raise _conflict(
                "mfa_required_for_staff", "platform staff accounts must keep two-factor on"
            )
        orgs = await self.required_by(user)
        if orgs:
            raise _conflict(
                "mfa_required_by_org",
                "an organization you belong to requires two-factor authentication",
                details=[{"organization_slug": o.slug, "organization_name": o.name} for o in orgs],
            )
        self._check_password(user, password)
        await self._check_signed_in_code(user, code, info)
        user.totp_secret_enc = None
        user.totp_enabled_at = None
        user.totp_last_step = None
        await self.db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))
        await self._audit(user, info, "account.mfa_disabled")
        await self.db.commit()

    async def regenerate_recovery_codes(
        self, user: PlatformUser, *, code: str, info: RequestInfo
    ) -> list[str]:
        if not user.mfa_enabled:
            raise _conflict("mfa_not_enabled", "two-factor authentication is not on")
        await self._check_signed_in_code(user, code, info, allow_recovery=False)
        codes = await self._new_recovery_codes(user)
        await self._audit(user, info, "account.mfa_recovery_codes_regenerated")
        await self.db.commit()
        return codes

    # -- operators -------------------------------------------------------------------------

    async def reset_by_operator(
        self, user: PlatformUser, *, actor: PlatformUser, reason: str, info: RequestInfo
    ) -> PlatformUser:
        """A person lost their authenticator and their recovery codes: an operator clears TOTP
        and signs them out everywhere. Staff must enrol again at their next sign-in."""
        user.totp_secret_enc = None
        user.totp_enabled_at = None
        user.totp_last_step = None
        await self.db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))
        await self.auth.revoke_all_sessions(user)
        await self._audit(
            user, info, "admin.user_mfa_reset", actor=actor, detail={"reason": reason}
        )
        await self.db.commit()
        return user
