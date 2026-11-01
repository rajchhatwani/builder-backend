"""Authentication business logic (generated). Routers stay thin; everything stateful is here."""

import datetime as dt
import hmac
import uuid
from typing import Any
from urllib.parse import quote

import sqlalchemy as sa
import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import config, identity, security
from app.auth.delivery import DeliveryError, Mailer, SmsSender
from app.auth.models import AuthInvitation, AuthTenant, AuthUser, AuthVerificationCode
from app.auth.tokens import TokenStore
from app.core.errors import AppError, ConflictError

logger = structlog.get_logger()

# Purposes of a stored verification code, and the channel that delivers each.
EMAIL_VERIFY = "email_verify"
MAGIC_LOGIN = "magic_login"
PASSWORD_RESET = "password_reset"
SMS_LOGIN = "sms_login"
PHONE_VERIFY = "phone_verify"
_EMAIL, _SMS = "email", "sms"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def invalid_credentials() -> AppError:
    return AppError("invalid_credentials", "invalid email or password", 401)


def invalid_code() -> AppError:
    return AppError("invalid_code", "the code or link is invalid or has expired", 400)


def effective_roles(roles: list[str]) -> set[str]:
    """The user's roles plus every role they inherit from."""
    result: set[str] = set()
    pending = list(roles)
    while pending:
        role = pending.pop()
        if role in result:
            continue
        result.add(role)
        parent = config.ROLE_PARENTS.get(role)
        if parent is not None:
            pending.append(parent)
    return result


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = config.get_auth_settings()
        self.tokens = TokenStore(session)

    # --- accounts -----------------------------------------------------------------

    async def register(self, data: dict[str, Any], mailer: Mailer) -> AuthUser:
        fields = dict(data)
        email, password, phone = fields.pop("email"), fields.pop("password"), fields.pop("phone")
        chosen = list(fields.pop("roles", []))
        tenant_name = fields.pop("tenant_name", None)
        invitation = await self._claim_invitation(email, fields.pop("invite_token", None))
        tenant_id, founder_roles = await self._place_in_tenant(invitation, tenant_name)
        invited = [r for r in (invitation.roles if invitation else []) if r in config.ROLE_PARENTS]
        user = AuthUser(
            email=email,
            phone=phone,
            password_hash=security.hash_password(password),
            roles=list(dict.fromkeys([*config.DEFAULT_ROLES, *chosen, *invited, *founder_roles])),
            **({"tenant_id": tenant_id} if config.MULTI_TENANT else {}),
            # Following an invitation sent to this address proves the user controls it.
            email_verified_at=_now() if invitation is not None else None,
            **fields,
        )
        self.session.add(user)
        if invitation is not None:
            invitation.accepted_at = _now()
        try:
            await self.session.flush()
            await identity.add_identity(
                self.session,
                user.id,
                issuer=config.ISSUER,
                subject=str(user.id),
                provider=config.PROVIDER,
                email=email,
                email_verified=user.email_verified_at is not None,
            )
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("an account with that email or phone number already exists") from exc
        await self.session.commit()
        if config.EMAIL_VERIFICATION_REQUIRED and user.email_verified_at is None:
            await self._send_email_link(user, EMAIL_VERIFY, mailer)
        return user

    # --- tenants ------------------------------------------------------------------

    async def _place_in_tenant(
        self, invitation: AuthInvitation | None, tenant_name: str | None
    ) -> tuple[uuid.UUID | None, list[str]]:
        """Which tenant a new user joins, and the roles that earns them.

        An invitation joins the inviter's tenant. Without one, the user creates a new
        tenant and starts as its admin."""
        if not config.MULTI_TENANT:
            return None, []
        if invitation is not None:
            return invitation.tenant_id, []  # type: ignore[attr-defined]
        if not tenant_name:
            raise AppError(
                "tenant_required",
                "tenant_name is required to create your tenant (or sign up with an invitation)",
                422,
            )
        tenant = AuthTenant(name=tenant_name)
        self.session.add(tenant)
        await self.session.flush()
        return tenant.id, [config.ADMIN_ROLE]

    async def get_tenant(self, user: AuthUser) -> AuthTenant:
        tenant = await self.session.get(AuthTenant, user.tenant_id)  # type: ignore[attr-defined]
        if tenant is None:  # unreachable: the foreign key forbids it
            raise AppError("not_found", "tenant not found", 404)
        return tenant

    # --- invitations --------------------------------------------------------------

    async def _claim_invitation(self, email: str, token: str | None) -> AuthInvitation | None:
        """Look up the invitation a registration presents. Raises when one is required."""
        if not config.INVITATIONS_ENABLED:
            return None
        if token is None:
            if config.INVITE_ONLY:
                raise AppError("invite_required", "registration is by invitation only", 403)
            return None
        stmt = (
            sa.select(AuthInvitation)
            .where(
                AuthInvitation.token_hash == security.hash_secret(token),
                AuthInvitation.accepted_at.is_(None),
                AuthInvitation.expires_at > _now(),
            )
            .with_for_update()
        )
        invitation = (await self.session.execute(stmt)).scalar_one_or_none()
        if invitation is None or invitation.email != email:
            raise AppError(
                "invalid_invitation",
                "the invitation is invalid, expired, already used or for another address",
                400,
            )
        return invitation

    async def create_invitation(
        self, inviter: AuthUser, email: str, roles: list[str], mailer: Mailer
    ) -> AuthInvitation:
        if await self.by_email(email) is not None:
            raise ConflictError("an account with that email already exists")
        token = security.new_token()
        invitation = AuthInvitation(
            email=email,
            roles=sorted(set(roles)),
            token_hash=security.hash_secret(token),
            invited_by_id=inviter.id,
            expires_at=_now() + dt.timedelta(days=config.INVITATION_TTL_DAYS),
            # The invitation joins the inviter's own tenant, never another.
            **({"tenant_id": inviter.tenant_id} if config.MULTI_TENANT else {}),  # type: ignore[attr-defined]
        )
        self.session.add(invitation)
        await self.session.commit()
        body = (
            f"You have been invited to {config.APP_NAME}. Create your account (valid for "
            f"{config.INVITATION_TTL_DAYS} days):\n\n{self._link('/accept-invite', token)}\n\n"
            "If you were not expecting this, you can ignore this message.\n"
        )
        try:
            await mailer.send(email, f"You are invited to {config.APP_NAME}", body)
        except (DeliveryError, AppError) as exc:
            # The inviter needs to know, so unlike other mail this failure is reported.
            logger.error("auth_delivery_failed", purpose="invitation", error=str(exc))
            await self.session.delete(invitation)
            await self.session.commit()
            raise AppError("delivery_failed", "the invitation email could not be sent", 502) from exc
        return invitation

    async def list_invitations(self, admin: AuthUser) -> list[AuthInvitation]:
        stmt = (
            sa.select(AuthInvitation)
            .where(AuthInvitation.accepted_at.is_(None), AuthInvitation.expires_at > _now())
            .order_by(AuthInvitation.created_at.desc())
            .limit(200)
        )
        if config.MULTI_TENANT:
            stmt = stmt.where(AuthInvitation.tenant_id == admin.tenant_id)  # type: ignore[attr-defined]
        return list((await self.session.execute(stmt)).scalars())

    async def revoke_invitation(self, admin: AuthUser, invitation_id: uuid.UUID) -> None:
        stmt = sa.delete(AuthInvitation).where(
            AuthInvitation.id == invitation_id, AuthInvitation.accepted_at.is_(None)
        )
        if config.MULTI_TENANT:
            stmt = stmt.where(AuthInvitation.tenant_id == admin.tenant_id)  # type: ignore[attr-defined]
        result = await self.session.execute(stmt)
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise AppError("not_found", "invitation not found", 404)
        await self.session.commit()

    async def by_email(self, email: str) -> AuthUser | None:
        stmt = sa.select(AuthUser).where(AuthUser.email == email, AuthUser.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def by_phone(self, phone: str) -> AuthUser | None:
        stmt = sa.select(AuthUser).where(AuthUser.phone == phone, AuthUser.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def authenticate(self, email: str, password: str) -> AuthUser:
        user = await self.by_email(email)
        # Always spend one password hash so unknown accounts take as long as known ones.
        stored = user.password_hash if user is not None else security.DUMMY_PASSWORD_HASH
        valid = security.verify_password(password, stored)
        if user is None or not valid:
            raise invalid_credentials()
        self._ensure_can_sign_in(user)
        if config.EMAIL_VERIFICATION_REQUIRED and user.email_verified_at is None:
            raise AppError("email_not_verified", "verify your email address before signing in", 403)
        return user

    @staticmethod
    def _ensure_can_sign_in(user: AuthUser) -> None:
        if not user.is_active or user.deleted_at is not None:
            raise AppError("account_disabled", "this account is disabled", 403)

    async def change_password(self, user: AuthUser, current: str, new: str) -> None:
        if not security.verify_password(current, user.password_hash):
            raise invalid_credentials()
        user.password_hash = security.hash_password(new)
        await self._revoke_all_refresh_tokens(user.id)
        await self.session.commit()

    async def delete_account(self, user: AuthUser) -> None:
        await self._revoke_all_refresh_tokens(user.id)
        if config.HARD_DELETE:
            await self.session.execute(sa.delete(AuthUser).where(AuthUser.id == user.id))
        else:
            user.is_active = False
            user.deleted_at = _now()
        await self.session.commit()

    # --- tokens -------------------------------------------------------------------

    async def issue_tokens(
        self, user: AuthUser, family_id: uuid.UUID | None = None
    ) -> tuple[str, str, int]:
        ttl = config.ACCESS_TOKEN_TTL_MINUTES * 60
        family_id = family_id or uuid.uuid4()
        if not await identity.open_session(
            self.session, user.id, config.ISSUER, str(family_id)
        ):
            raise AppError("invalid_token", "the refresh token is invalid", 401)
        access = security.create_access_token(
            user.id,
            sorted(user.roles),
            key=self.settings.jwt_key,
            ttl_seconds=ttl,
            tenant_id=getattr(user, "tenant_id", None),
            issuer=config.ISSUER,
            session_id=str(family_id),
        )
        refresh = security.new_token()
        await self.tokens.add(
            user.id,
            family_id,
            security.hash_secret(refresh),
            _now() + dt.timedelta(days=config.REFRESH_TOKEN_TTL_DAYS),
        )
        user.last_login_at = _now()
        await self.session.commit()
        return access, refresh, ttl

    async def refresh(self, raw_token: str) -> tuple[str, str, int]:
        rotation = await self.tokens.rotate(security.hash_secret(raw_token))
        if rotation.status != "ok" or rotation.user_id is None:
            message = "the refresh token has expired" if rotation.status == "expired" else (
                "the refresh token is invalid"
            )
            raise AppError("invalid_token", message, 401)
        user = await self.session.get(AuthUser, rotation.user_id)
        if user is None or not user.is_active or user.deleted_at is not None:
            raise AppError("invalid_token", "the refresh token is invalid", 401)
        return await self.issue_tokens(user, family_id=rotation.family_id)

    async def logout(self, raw_token: str) -> None:
        family_id = await self.tokens.revoke_family_of(security.hash_secret(raw_token))
        await self.session.commit()
        if family_id is not None:
            await identity.end_session(self.session, config.ISSUER, str(family_id), "logout")

    async def _revoke_all_refresh_tokens(self, user_id: uuid.UUID) -> None:
        await self.tokens.revoke_all(user_id)
        await identity.end_sessions_of_user(self.session, user_id, "credentials_changed")

    # --- verification codes -------------------------------------------------------

    async def _store_code(
        self, user: AuthUser, purpose: str, channel: str, secret: str, ttl: dt.timedelta
    ) -> None:
        """Save a hash of `secret`; any earlier unused code for the same purpose dies."""
        now = _now()
        await self.session.execute(
            sa.update(AuthVerificationCode)
            .where(
                AuthVerificationCode.user_id == user.id,
                AuthVerificationCode.purpose == purpose,
                AuthVerificationCode.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
        self.session.add(
            AuthVerificationCode(
                user_id=user.id,
                purpose=purpose,
                channel=channel,
                code_hash=self._code_hash(user.id, purpose, secret),
                expires_at=now + ttl,
            )
        )
        await self.session.commit()

    @staticmethod
    def _code_hash(user_id: uuid.UUID, purpose: str, secret: str) -> str:
        return security.hash_secret(f"{user_id}:{purpose}:{secret}")

    async def _consume_link(self, token: str, purpose: str) -> AuthUser:
        """Redeem an emailed link token. The token alone identifies the account."""
        # Links carry the user id so the stored hash can bind it: "<user_id>.<secret>".
        user_part, _, secret = token.partition(".")
        try:
            user_id = uuid.UUID(user_part)
        except ValueError as exc:
            raise invalid_code() from exc
        stmt = (
            sa.select(AuthVerificationCode)
            .where(
                AuthVerificationCode.user_id == user_id,
                AuthVerificationCode.purpose == purpose,
                AuthVerificationCode.code_hash == self._code_hash(user_id, purpose, secret),
                AuthVerificationCode.consumed_at.is_(None),
                AuthVerificationCode.expires_at > _now(),
            )
            .with_for_update()
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        user = await self.session.get(AuthUser, user_id) if row is not None else None
        if row is None or user is None or user.deleted_at is not None:
            raise invalid_code()
        row.consumed_at = _now()
        return user

    async def _consume_otp(self, user: AuthUser, purpose: str, code: str) -> None:
        """Check a six-digit SMS code; wrong guesses are counted and cap out."""
        stmt = (
            sa.select(AuthVerificationCode)
            .where(
                AuthVerificationCode.user_id == user.id,
                AuthVerificationCode.purpose == purpose,
                AuthVerificationCode.consumed_at.is_(None),
                AuthVerificationCode.expires_at > _now(),
            )
            .order_by(AuthVerificationCode.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None or row.attempts >= config.MAX_OTP_ATTEMPTS:
            raise invalid_code()
        row.attempts += 1
        if not hmac.compare_digest(row.code_hash, self._code_hash(user.id, purpose, code)):
            await self.session.commit()  # keep the failed attempt
            raise invalid_code()
        row.consumed_at = _now()

    # --- email --------------------------------------------------------------------

    def _link(self, path: str, token: str) -> str:
        base = (config.APP_URL or "").rstrip("/")
        return f"{base}{path}?token={quote(token)}"

    async def _send_email_link(self, user: AuthUser, purpose: str, mailer: Mailer) -> None:
        secret = security.new_token()
        ttl = dt.timedelta(hours=config.VERIFICATION_TTL_HOURS)
        if purpose != EMAIL_VERIFY:
            ttl = dt.timedelta(minutes=config.OTP_TTL_MINUTES)
        await self._store_code(user, purpose, _EMAIL, secret, ttl)
        token = f"{user.id}.{secret}"
        subjects = {
            EMAIL_VERIFY: (f"Verify your email for {config.APP_NAME}", "/verify-email",
                           "Confirm your email address"),
            MAGIC_LOGIN: (f"Your sign-in link for {config.APP_NAME}", "/magic-link",
                          "Sign in"),
            PASSWORD_RESET: (f"Reset your {config.APP_NAME} password", "/reset-password",
                             "Reset your password"),
        }
        subject, path, action = subjects[purpose]
        minutes = int(ttl.total_seconds() // 60)
        body = (
            f"{action} by opening this link (valid for {minutes} minutes):\n\n"
            f"{self._link(path, token)}\n\n"
            "If you did not request this, you can ignore this message.\n"
        )
        await self._deliver(lambda: mailer.send(user.email, subject, body), purpose)

    async def _deliver(self, send: Any, purpose: str) -> None:
        """Delivery problems are logged, never shown: callers must not learn whether an
        address exists, and a mail outage should not turn into a failed sign-up."""
        try:
            await send()
        except (DeliveryError, AppError) as exc:
            logger.error("auth_delivery_failed", purpose=purpose, error=str(exc))

    async def resend_verification(self, email: str, mailer: Mailer) -> None:
        user = await self.by_email(email)
        if user is not None and user.email_verified_at is None and user.is_active:
            await self._send_email_link(user, EMAIL_VERIFY, mailer)

    async def verify_email(self, token: str) -> AuthUser:
        user = await self._consume_link(token, EMAIL_VERIFY)
        user.email_verified_at = user.email_verified_at or _now()
        await self.session.commit()
        return user

    async def request_magic_link(self, email: str, mailer: Mailer) -> None:
        user = await self.by_email(email)
        if user is not None and user.is_active:
            await self._send_email_link(user, MAGIC_LOGIN, mailer)

    async def consume_magic_link(self, token: str) -> AuthUser:
        user = await self._consume_link(token, MAGIC_LOGIN)
        self._ensure_can_sign_in(user)
        # Opening a link sent to the address proves the user controls it.
        user.email_verified_at = user.email_verified_at or _now()
        await self.session.commit()
        return user

    # --- sms ----------------------------------------------------------------------

    async def _send_sms_code(self, user: AuthUser, purpose: str, sms: SmsSender) -> None:
        if user.phone is None:
            return
        code = security.new_otp()
        ttl = dt.timedelta(minutes=config.OTP_TTL_MINUTES)
        await self._store_code(user, purpose, _SMS, code, ttl)
        body = f"Your {config.APP_NAME} code is {code}. It expires in {config.OTP_TTL_MINUTES} minutes."
        phone = user.phone
        await self._deliver(lambda: sms.send(phone, body), purpose)

    async def request_phone_verification(self, user: AuthUser, sms: SmsSender) -> None:
        if user.phone is None:
            raise AppError("no_phone", "add a phone number to your account first", 400)
        await self._send_sms_code(user, PHONE_VERIFY, sms)

    async def confirm_phone_verification(self, user: AuthUser, code: str) -> None:
        await self._consume_otp(user, PHONE_VERIFY, code)
        user.phone_verified_at = _now()
        await self.session.commit()

    async def _verified_phone_user(self, phone: str) -> AuthUser | None:
        user = await self.by_phone(phone)
        if user is None or not user.is_active or user.phone_verified_at is None:
            return None
        return user

    async def request_sms_login(self, phone: str, sms: SmsSender) -> None:
        user = await self._verified_phone_user(phone)
        if user is not None:
            await self._send_sms_code(user, SMS_LOGIN, sms)

    async def verify_sms_login(self, phone: str, code: str) -> AuthUser:
        user = await self._verified_phone_user(phone)
        if user is None:
            # Spend comparable work on unknown numbers.
            security.verify_password(code, security.DUMMY_PASSWORD_HASH)
            raise invalid_code()
        await self._consume_otp(user, SMS_LOGIN, code)
        await self.session.commit()
        return user

    # --- password reset -----------------------------------------------------------

    async def request_password_reset(
        self, email: str | None, phone: str | None, mailer: Mailer, sms: SmsSender
    ) -> None:
        if email is not None and config.EMAIL_MAGIC_LINK_ENABLED:
            user = await self.by_email(email)
            if user is not None and user.is_active:
                await self._send_email_link(user, PASSWORD_RESET, mailer)
        elif phone is not None and config.SMS_OTP_ENABLED:
            user = await self._verified_phone_user(phone)
            if user is not None:
                await self._send_sms_code(user, PASSWORD_RESET, sms)
        else:
            raise AppError("reset_unavailable", "that reset method is not enabled", 400)

    async def confirm_password_reset(
        self, new_password: str, token: str | None, phone: str | None, code: str | None
    ) -> None:
        if token is not None:
            if not config.EMAIL_MAGIC_LINK_ENABLED:
                raise AppError("reset_unavailable", "that reset method is not enabled", 400)
            user = await self._consume_link(token, PASSWORD_RESET)
        else:
            if not config.SMS_OTP_ENABLED or phone is None or code is None:
                raise AppError("reset_unavailable", "that reset method is not enabled", 400)
            found = await self._verified_phone_user(phone)
            if found is None:
                security.verify_password(code, security.DUMMY_PASSWORD_HASH)
                raise invalid_code()
            await self._consume_otp(found, PASSWORD_RESET, code)
            user = found
        user.password_hash = security.hash_password(new_password)
        await self._revoke_all_refresh_tokens(user.id)
        await self.session.commit()
