"""Enterprise SSO per organization (PLATFORM_SAAS_PLAN §4.2, §12.D.1–D.4).

Configuration (org admins): one SAML or OIDC connection, e-mail domains proven over DNS, and
activation, gated on `plans.allow_sso` with the usual 402 + `quota.denied` (§6.2).

Sign-in (anyone): tenant-first discovery by e-mail domain, a redirect to the IdP, and back. The
rules that keep one tenant's IdP from reaching anyone else:
  - the asserted e-mail must be on a domain **this** org has verified in DNS;
  - a login state is single-use, short-lived and bound to the browser that started it (cookie
    hash), which is what makes SAML `InResponseTo` / OIDC `state` stop replays and login CSRF;
  - platform staff never sign in through a customer's IdP;
  - JIT (§4.2 step 3) only on login, seat-checked like an invite, never as owner.
"""

import hashlib
import hmac
import os
import re
import secrets
import urllib.parse
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import crypto
from app.core import platform_security as sec
from app.exceptions import AppError
from app.models.enums import AccountStatus, AuditResult, OrgKind, OrgRole, PlatformRole
from app.models.platform import Organization, OrganizationMember, PlatformUser
from app.models.sso import SsoConnection, SsoDomain, SsoLoginRequest
from app.schemas.sso import SsoConfigUpdate
from app.services import audit_service, dns_txt, oidc, saml
from app.services.organization_service import OrganizationService
from app.services.platform_auth_service import (
    PlatformAuthService,
    RequestInfo,
    Session,
    normalize_email,
)

log = structlog.get_logger()

VERIFICATION_LABEL = "_builder-verification"
VERIFICATION_PREFIX = "builder-verification="
# Password hash of accounts created by SSO: not a valid scrypt string, so no password matches.
SSO_ONLY_PASSWORD_HASH = sec.SSO_ONLY_PASSWORD_HASH
BROWSER_COOKIE = "bb_sso"

# Consumer mailbox providers: nobody may claim these for their org.
PUBLIC_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "msn.com",
        "yahoo.com",
        "ymail.com",
        "icloud.com",
        "me.com",
        "mac.com",
        "aol.com",
        "proton.me",
        "protonmail.com",
        "gmx.com",
        "gmx.de",
        "web.de",
        "mail.com",
        "yandex.com",
        "yandex.ru",
        "zoho.com",
        "qq.com",
        "163.com",
        "fastmail.com",
        "hey.com",
        "tutanota.com",
    }
)
_LABEL_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_BROWSER_RE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")


def _now() -> datetime:
    return datetime.now(UTC)


class SsoLoginError(Exception):
    """A sign-in that must not happen. `reason` goes to the audit log and the login page."""

    def __init__(self, reason: str, *, email: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.email = email


@dataclass(frozen=True)
class LoginStart:
    redirect_url: str
    browser: str  # the cookie value; only its hash is stored


@dataclass(frozen=True)
class SsoOutcome:
    """How an IdP callback ended: a session (a real sign-in), or the result of an admin's
    "test with my own e-mail" round trip ('ok' or a reason), which never signs anyone in."""

    session: Session | None = None
    test_result: str | None = None


@dataclass(frozen=True)
class SsoCheckItem:
    name: str
    status: str  # 'ok' | 'warning' | 'error'
    detail: str | None = None


@dataclass(frozen=True)
class SsoCheck:
    protocol: str | None
    active: bool
    items: list[SsoCheckItem]

    @property
    def ok(self) -> bool:
        return all(i.status != "error" for i in self.items)


# "Test with my own e-mail" (§12.D.6): a short-lived ticket in the login URL names the admin
# who started it; it only ever starts a test, never a sign-in.
TEST_TICKET_AUDIENCE = "builder-sso-test"
TEST_TICKET_SECONDS = 300


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def normalize_domain(raw: str) -> str:
    domain = raw.strip().lower().lstrip("@").rstrip(".")
    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise AppError(
            code="invalid_domain", message="not a valid domain", status_code=422
        ) from exc
    labels = domain.split(".")
    if (
        len(domain) > 253
        or len(labels) < 2
        or not all(_LABEL_RE.match(label) for label in labels)
        or labels[-1].isdigit()
    ):
        raise AppError(code="invalid_domain", message="not a valid domain", status_code=422)
    if domain in PUBLIC_EMAIL_DOMAINS:
        raise AppError(
            code="public_email_domain",
            message="public e-mail providers can't be claimed for an organization",
            status_code=422,
        )
    return domain


def _domain_key() -> bytes:
    secret = os.environ.get("SECRET_KEY", "")
    if not secret:
        raise RuntimeError("SECRET_KEY is not set")
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"builder-sso-domain-v1"
    ).derive(secret.encode())


def dns_token_for(organization_id: uuid.UUID, domain: str) -> str:
    """Deterministic per (org, domain): an org's TXT value proves that org, and no other."""
    mac = hmac.new(_domain_key(), f"{organization_id}:{domain}".encode(), hashlib.sha256)
    return mac.hexdigest()[:40]


class SsoService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.db = session
        self.settings = settings
        self.orgs = OrganizationService(session)

    # -- URLs ------------------------------------------------------------------------------

    def _api(self, path: str) -> str:
        return self.settings.public_api_url.rstrip("/") + path

    def sp_entity_id(self, slug: str) -> str:
        return self._api(f"/sso/metadata/{slug}")

    def acs_url(self, slug: str) -> str:
        return self._api(f"/sso/saml/{slug}/acs")

    def oidc_redirect_uri(self, slug: str) -> str:
        return self._api(f"/sso/oidc/{slug}/callback")

    def login_url(self, slug: str, login_hint: str | None = None) -> str:
        url = self._api(f"/sso/{slug}/login")
        if login_hint:
            url += "?" + urllib.parse.urlencode({"login_hint": login_hint})
        return url

    def app_url(self, fragment: str) -> str:
        return self.settings.public_app_url.rstrip("/") + "/#/" + fragment

    @staticmethod
    def dns_record(domain: SsoDomain) -> tuple[str, str]:
        return f"{VERIFICATION_LABEL}.{domain.domain}", VERIFICATION_PREFIX + domain.dns_token

    # -- reads -----------------------------------------------------------------------------

    async def connection(self, organization_id: uuid.UUID) -> SsoConnection | None:
        return (
            await self.db.execute(
                select(SsoConnection).where(SsoConnection.organization_id == organization_id)
            )
        ).scalar_one_or_none()

    async def domains(self, organization_id: uuid.UUID) -> list[SsoDomain]:
        return list(
            (
                await self.db.execute(
                    select(SsoDomain)
                    .where(SsoDomain.organization_id == organization_id)
                    .order_by(SsoDomain.domain)
                )
            ).scalars()
        )

    async def allowed_by_plan(self, organization_id: uuid.UUID) -> bool:
        plan, _sub = await self.orgs.plan_and_subscription(organization_id)
        return plan.allow_sso

    # -- configuration ---------------------------------------------------------------------

    async def _require_sso_allowed(self, org: Organization, actor: PlatformUser) -> None:
        """§6.2: SSO on/off follows `plans.allow_sso`; refusals are 402 + `quota.denied`."""
        if org.kind is OrgKind.personal:
            raise AppError(
                code="sso_not_for_personal_orgs",
                message="SSO is for team organizations; create one first",
                status_code=409,
            )
        plan, _sub = await self.orgs.plan_and_subscription(org.id)
        if not plan.allow_sso:
            raise await self.orgs._deny(  # noqa: SLF001 — the one shared 402 path
                org.id,
                code="sso_not_in_plan",
                resource="sso",
                plan=plan,
                cap=None,
                used=0,
                message=f"plan '{plan.id}' doesn't include single sign-on; upgrade to use it",
                actor_id=actor.id,
                actor_email=actor.email,
                reason="feature",
            )

    def _check_url(self, url: str | None, field: str) -> str:
        if not url or not url.strip():
            raise AppError(
                code="invalid_sso_config", message=f"{field} is required", status_code=422
            )
        url = url.strip()
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("https", "http") or not parts.hostname or parts.username:
            raise AppError(code="invalid_url", message=f"{field} must be a URL", status_code=422)
        if parts.scheme != "https" and self.settings.sso_require_https:
            raise AppError(code="insecure_url", message=f"{field} must use https", status_code=422)
        return url

    async def save_config(
        self, org: Organization, body: SsoConfigUpdate, actor: PlatformUser, info: RequestInfo
    ) -> SsoConnection:
        await self._require_sso_allowed(org, actor)
        conn = await self.connection(org.id)
        created = conn is None
        if conn is None:
            conn = SsoConnection(organization_id=org.id, protocol=body.protocol)
        switched = conn.protocol != body.protocol
        conn.protocol = body.protocol
        if body.protocol == "saml":
            entity_id = (body.idp_entity_id or "").strip()
            if not entity_id:
                raise AppError(
                    code="invalid_sso_config", message="idp_entity_id is required", status_code=422
                )
            if not body.idp_cert_pem:
                raise AppError(
                    code="invalid_sso_config", message="idp_cert_pem is required", status_code=422
                )
            try:
                cert = saml.normalize_cert(body.idp_cert_pem)
            except saml.SamlError as exc:
                raise AppError(
                    code="invalid_certificate",
                    message="idp_cert_pem is not an X.509 certificate",
                    status_code=422,
                ) from exc
            conn.idp_entity_id = entity_id
            conn.idp_sso_url = self._check_url(body.idp_sso_url, "idp_sso_url")
            conn.idp_cert_pem = cert
            conn.oidc_discovery_url = conn.oidc_client_id = None
            conn.oidc_client_secret_enc = None
        else:
            client_id = (body.oidc_client_id or "").strip()
            if not client_id:
                raise AppError(
                    code="invalid_sso_config", message="oidc_client_id is required", status_code=422
                )
            conn.oidc_discovery_url = self._check_url(body.oidc_discovery_url, "oidc_discovery_url")
            conn.oidc_client_id = client_id
            if body.oidc_client_secret:
                encrypted = crypto.encrypt(body.oidc_client_secret)
                assert encrypted is not None
                conn.oidc_client_secret_enc = encrypted.encode()
            elif switched or conn.oidc_client_secret_enc is None:
                raise AppError(
                    code="oidc_client_secret_required",
                    message="oidc_client_secret is required",
                    status_code=422,
                )
            conn.idp_entity_id = conn.idp_sso_url = conn.idp_cert_pem = None
        conn.jit_enabled = body.jit_enabled
        conn.jit_role = body.jit_role
        if body.trust_unverified_email is not None:
            conn.trust_unverified_email = body.trust_unverified_email
        elif created:
            conn.trust_unverified_email = False
        if created:
            self.db.add(conn)
        await self._audit(
            org,
            actor,
            info,
            "sso.config_updated",
            # Names only: never the certificate, the client secret or the URLs' contents.
            detail={
                "protocol": body.protocol,
                "created": created,
                "active": conn.active,
                "jit_enabled": body.jit_enabled,
                "jit_role": body.jit_role,
                "trust_unverified_email": conn.trust_unverified_email,
                "client_secret_changed": bool(body.oidc_client_secret),
            },
        )
        await self.db.commit()
        return conn

    async def set_active(
        self, org: Organization, active: bool, actor: PlatformUser, info: RequestInfo
    ) -> SsoConnection:
        if active:
            await self._require_sso_allowed(org, actor)
        conn = await self.connection(org.id)
        if conn is None:
            raise AppError(
                code="sso_not_configured",
                message="save the SSO configuration first",
                status_code=409,
            )
        if active and not any(d.verified_at for d in await self.domains(org.id)):
            raise AppError(
                code="no_verified_domain",
                message="verify at least one e-mail domain before turning SSO on",
                status_code=409,
            )
        if conn.active != active:
            conn.active = active
            await self._audit(
                org,
                actor,
                info,
                "sso.activated" if active else "sso.deactivated",
                detail={"protocol": conn.protocol},
            )
        await self.db.commit()
        return conn

    async def delete_config(
        self, org: Organization, actor: PlatformUser, info: RequestInfo
    ) -> None:
        conn = await self.connection(org.id)
        if conn is None:
            raise AppError(code="not_found", message="no SSO configuration", status_code=404)
        await self.db.delete(conn)
        await self._audit(org, actor, info, "sso.deleted", detail={"protocol": conn.protocol})
        await self.db.commit()

    # -- domains (§12.D.2) -----------------------------------------------------------------

    async def add_domain(
        self, org: Organization, raw: str, actor: PlatformUser, info: RequestInfo
    ) -> SsoDomain:
        await self._require_sso_allowed(org, actor)
        domain = normalize_domain(raw)
        row = await self.db.get(SsoDomain, domain, with_for_update=True)
        replaced = False
        if row is not None and row.organization_id == org.id:
            return row
        if row is not None and row.verified_at is not None:
            raise AppError(
                code="domain_taken",
                message="this domain is verified by another organization",
                status_code=409,
            )
        if row is not None:
            # An unproven claim never blocks whoever can prove it: the claim moves, and since
            # tokens are per org, the previous claimant's DNS value no longer verifies anything.
            row.organization_id = org.id
            row.dns_token = dns_token_for(org.id, domain)
            row.created_at = _now()
            replaced = True
        else:
            row = SsoDomain(
                domain=domain, organization_id=org.id, dns_token=dns_token_for(org.id, domain)
            )
            self.db.add(row)
        await self._audit(
            org,
            actor,
            info,
            "sso.domain_added",
            target_type="sso_domain",
            target_id=domain,
            detail={"domain": domain, "replaced_unverified_claim": replaced},
        )
        await self.db.commit()
        return row

    async def _own_domain(self, org: Organization, raw: str) -> SsoDomain:
        try:
            domain = normalize_domain(raw)
        except AppError as exc:
            raise AppError(code="not_found", message="domain not found", status_code=404) from exc
        row = await self.db.get(SsoDomain, domain)
        if row is None or row.organization_id != org.id:
            raise AppError(code="not_found", message="domain not found", status_code=404)
        return row

    async def verify_domain(
        self, org: Organization, raw: str, actor: PlatformUser, info: RequestInfo
    ) -> SsoDomain:
        row = await self._own_domain(org, raw)
        if row.verified_at is not None:
            return row
        name, value = self.dns_record(row)
        found = await dns_txt.txt_records(name)
        if not any(hmac.compare_digest(txt.strip(), value) for txt in found):
            await self._audit(
                org,
                actor,
                info,
                "sso.domain_verified",
                result=AuditResult.denied,
                target_type="sso_domain",
                target_id=row.domain,
                detail={"domain": row.domain, "reason": "txt_record_missing"},
            )
            await self.db.commit()
            raise AppError(
                code="domain_not_verified",
                message=f"TXT record not found at {name}; DNS changes can take a while",
                status_code=409,
                details=[
                    {"dns_record_type": "TXT", "dns_record_name": name, "dns_record_value": value}
                ],
            )
        row.verified_at = _now()
        await self._audit(
            org,
            actor,
            info,
            "sso.domain_verified",
            target_type="sso_domain",
            target_id=row.domain,
            detail={"domain": row.domain},
        )
        await self.db.commit()
        return row

    async def remove_domain(
        self, org: Organization, raw: str, actor: PlatformUser, info: RequestInfo
    ) -> None:
        row = await self._own_domain(org, raw)
        conn = await self.connection(org.id)
        if conn is not None and conn.active and row.verified_at is not None:
            others = [
                d for d in await self.domains(org.id) if d.verified_at and d.domain != row.domain
            ]
            if not others:
                raise AppError(
                    code="last_verified_domain",
                    message="turn SSO off before removing its last verified domain",
                    status_code=409,
                )
        await self.db.delete(row)
        await self._audit(
            org,
            actor,
            info,
            "sso.domain_removed",
            target_type="sso_domain",
            target_id=row.domain,
            detail={"domain": row.domain},
        )
        await self.db.commit()

    async def operator_release_domain(
        self, raw: str, actor: PlatformUser, reason: str, info: RequestInfo
    ) -> Organization:
        """Review F-008: a verified claim is otherwise permanent. A platform admin frees the
        domain (the domain's new owner, or a company that dropped it, would be locked out
        otherwise). If it was the org's last verified domain, SSO is switched off with it, since
        nobody could sign in through it any more. Returns the org that held the claim."""
        domain = normalize_domain(raw)
        row = await self.db.get(SsoDomain, domain, with_for_update=True)
        org = await self.db.get(Organization, row.organization_id) if row is not None else None
        if row is None or org is None:
            raise AppError(code="not_found", message="domain not found", status_code=404)
        was_verified = row.verified_at is not None
        await self.db.delete(row)
        await self.db.flush()
        sso_off = False
        conn = await self.connection(org.id)
        remaining = [d for d in await self.domains(org.id) if d.verified_at]
        if conn is not None and conn.active and not remaining:
            conn.active = False
            sso_off = True
        await self._audit(
            org,
            actor,
            info,
            "admin.sso_domain_released",
            target_type="sso_domain",
            target_id=domain,
            detail={
                "domain": domain,
                "was_verified": was_verified,
                "reason": reason,
                "sso_deactivated": sso_off,
            },
        )
        await self.db.commit()
        return org

    # -- sign-in ---------------------------------------------------------------------------

    async def _connection_for(
        self, org: Organization | None, *, allow_inactive: bool
    ) -> SsoConnection | None:
        if (
            org is None
            or org.deleted_at is not None
            or org.deletion_requested_at is not None
            or org.kind is not OrgKind.team
        ):
            return None
        conn = await self.connection(org.id)
        if conn is None or (not conn.active and not allow_inactive):
            return None
        if not await self.allowed_by_plan(org.id):
            return None
        return conn

    async def _usable(self, org: Organization | None) -> SsoConnection | None:
        """The org's connection if a login may use it right now, else None."""
        return await self._connection_for(org, allow_inactive=False)

    async def _for_callback(
        self, org: Organization | None, browser: str | None
    ) -> tuple[SsoConnection | None, SsoLoginRequest | None]:
        """The connection an IdP callback may use, and this browser's pending test if any.
        An inactive connection only serves the test that this browser started."""
        conn = await self._connection_for(org, allow_inactive=True)
        test = await self._pending_test(org.id, browser) if org is not None and conn else None
        if conn is not None and not conn.active and test is None:
            conn = None
        return conn, test

    async def _pending_test(
        self, organization_id: uuid.UUID, browser: str | None
    ) -> SsoLoginRequest | None:
        if not browser:
            return None
        return (
            await self.db.execute(
                select(SsoLoginRequest)
                .where(
                    SsoLoginRequest.organization_id == organization_id,
                    SsoLoginRequest.purpose == "test",
                    SsoLoginRequest.browser_hash == _hash(browser),
                    SsoLoginRequest.consumed_at.is_(None),
                    SsoLoginRequest.expires_at > _now(),
                )
                .order_by(SsoLoginRequest.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    # -- "test with my own e-mail" (§12.D.6) ----------------------------------------------

    async def create_test(self, org: Organization, actor: PlatformUser, info: RequestInfo) -> str:
        """The URL that runs one test login for `actor`. Works before SSO is switched on."""
        await self._require_sso_allowed(org, actor)
        if await self.connection(org.id) is None:
            raise AppError(
                code="sso_not_configured",
                message="save the SSO configuration before testing it",
                status_code=409,
            )
        claims = sec.access_claims(
            user_id=str(actor.id),
            audience=TEST_TICKET_AUDIENCE,
            token_version=actor.token_version,
            ttl_seconds=TEST_TICKET_SECONDS,
        )
        claims["org"] = str(org.id)
        await self._audit(org, actor, info, "sso.test_started")
        await self.db.commit()
        url = self._api(f"/sso/{org.slug}/login")
        return url + "?" + urllib.parse.urlencode({"test": sec.encode_jwt(claims)})

    async def _tester(self, ticket: str, org: Organization | None) -> PlatformUser:
        try:
            claims = sec.decode_jwt(ticket, audience=TEST_TICKET_AUDIENCE)
            user_id = uuid.UUID(claims["sub"])
        except (sec.TokenError, ValueError):
            raise SsoLoginError("invalid_test_ticket") from None
        if org is None or claims.get("org") != str(org.id):
            raise SsoLoginError("invalid_test_ticket")
        user = await self.db.get(PlatformUser, user_id)
        if (
            user is None
            or user.status is not AccountStatus.active
            or claims.get("tv") != user.token_version
        ):
            raise SsoLoginError("invalid_test_ticket")
        return user

    async def _finish_test(
        self,
        org: Organization,
        conn: SsoConnection,
        tester_id: uuid.UUID | None,
        email: str,
        protocol: str,
        info: RequestInfo,
    ) -> SsoOutcome:
        email = normalize_email(email)
        tester = await self.db.get(PlatformUser, tester_id) if tester_id else None
        verified = (
            await self.db.execute(
                select(SsoDomain).where(
                    SsoDomain.domain == email.rsplit("@", 1)[-1],
                    SsoDomain.organization_id == org.id,
                    SsoDomain.verified_at.is_not(None),
                )
            )
        ).scalar_one_or_none()
        if tester is None:
            result = "invalid_test_ticket"
        elif email != tester.email:
            result = "email_mismatch"
        elif verified is None:
            result = "email_domain_not_verified"
        else:
            result = "ok"
        return await self._record_test(org.id, tester_id, result, protocol, info, conn=conn)

    async def _record_test(
        self,
        organization_id: uuid.UUID,
        tester_id: uuid.UUID | None,
        result: str,
        protocol: str,
        info: RequestInfo,
        *,
        conn: SsoConnection | None = None,
    ) -> SsoOutcome:
        conn = conn or await self.connection(organization_id)
        tester = await self.db.get(PlatformUser, tester_id) if tester_id else None
        if conn is not None:
            conn.last_test_at = _now()
            conn.last_test_result = result[:60]
            conn.last_tested_by = tester.id if tester else None
        await audit_service.record(
            self.db,
            action="sso.test",
            result=AuditResult.ok if result == "ok" else AuditResult.denied,
            actor_id=tester.id if tester else None,
            actor_email=tester.email if tester else None,
            via="sso",
            organization_id=organization_id,
            target_type="organization",
            target_id=organization_id,
            client_ip=info.client_ip,
            request_id=info.request_id,
            detail={"protocol": protocol, "result": result},
        )
        await self.db.commit()
        return SsoOutcome(test_result=result)

    async def _test_failed(
        self,
        organization_id: uuid.UUID,
        test: SsoLoginRequest,
        reason: str,
        protocol: str,
        info: RequestInfo,
    ) -> SsoOutcome:
        tester_id, test_id = test.test_user_id, test.id
        await self.db.rollback()
        await self.db.execute(
            update(SsoLoginRequest)
            .where(SsoLoginRequest.id == test_id, SsoLoginRequest.consumed_at.is_(None))
            .values(consumed_at=_now())
        )
        return await self._record_test(organization_id, tester_id, reason, protocol, info)

    # -- connection check (customer admin "check" and the operator's test button) ---------

    async def check(self, org: Organization) -> SsoCheck:
        """What would stop SSO working, without signing anyone in. For OIDC this fetches the
        discovery document and the JWKS; for SAML it inspects the IdP certificate."""
        items: list[SsoCheckItem] = []
        allowed = await self.allowed_by_plan(org.id)
        items.append(
            SsoCheckItem(
                "plan", "ok" if allowed else "error", None if allowed else "sso_not_in_plan"
            )
        )
        verified = [d for d in await self.domains(org.id) if d.verified_at is not None]
        items.append(
            SsoCheckItem(
                "verified_domain",
                "ok" if verified else "error",
                ", ".join(d.domain for d in verified) or "no_verified_domain",
            )
        )
        conn = await self.connection(org.id)
        if conn is None:
            items.append(SsoCheckItem("configuration", "error", "sso_not_configured"))
            return SsoCheck(None, False, items)
        items.append(SsoCheckItem("configuration", "ok", conn.protocol))
        items.append(
            SsoCheckItem(
                "active", "ok" if conn.active else "warning", None if conn.active else "not_active"
            )
        )
        if conn.protocol == "saml":
            items.append(self._check_certificate(conn.idp_cert_pem))
        else:
            items.extend(await self._check_oidc(conn))
        if conn.last_test_result is not None:
            items.append(
                SsoCheckItem(
                    "last_test",
                    "ok" if conn.last_test_result == "ok" else "warning",
                    conn.last_test_result,
                )
            )
        else:
            items.append(SsoCheckItem("last_test", "warning", "never_tested"))
        return SsoCheck(conn.protocol, conn.active, items)

    @staticmethod
    def _check_certificate(pem: str | None) -> SsoCheckItem:
        if not pem:
            return SsoCheckItem("certificate", "error", "missing")
        try:
            not_after = datetime.fromisoformat(saml.cert_summary(pem)["not_after"])
        except ValueError:
            return SsoCheckItem("certificate", "error", "invalid_certificate")
        left = not_after - _now()
        if left.total_seconds() <= 0:
            return SsoCheckItem("certificate", "error", "expired")
        if left < timedelta(days=30):
            return SsoCheckItem("certificate", "warning", f"expires {not_after.date().isoformat()}")
        return SsoCheckItem("certificate", "ok", f"valid until {not_after.date().isoformat()}")

    async def _check_oidc(self, conn: SsoConnection) -> list[SsoCheckItem]:
        items = [
            SsoCheckItem(
                "client_secret",
                "ok" if conn.oidc_client_secret_enc else "error",
                None if conn.oidc_client_secret_enc else "oidc_client_secret_required",
            )
        ]
        common = {
            "allow_private": self.settings.sso_allow_private_idp,
            "require_https": self.settings.sso_require_https,
        }
        try:
            assert conn.oidc_discovery_url
            discovery = await oidc.fetch_discovery(conn.oidc_discovery_url, **common)
        except oidc.OidcError as exc:
            return [*items, SsoCheckItem("discovery", "error", exc.reason)]
        items.append(SsoCheckItem("discovery", "ok", discovery.issuer))
        try:
            keys = await oidc.fetch_jwks(discovery, **common)
        except oidc.OidcError as exc:
            return [*items, SsoCheckItem("jwks", "error", exc.reason)]
        count = len(keys.get("keys", []))
        items.append(SsoCheckItem("jwks", "ok" if count else "error", f"{count} key(s)"))
        return items

    async def discover(self, email: str) -> Organization | None:
        """§4.2 step 1: the org whose active SSO owns this e-mail's domain, if any."""
        email = normalize_email(email)
        if "@" not in email:
            return None
        domain = (
            await self.db.execute(
                select(SsoDomain).where(
                    SsoDomain.domain == email.rsplit("@", 1)[1], SsoDomain.verified_at.is_not(None)
                )
            )
        ).scalar_one_or_none()
        if domain is None:
            return None
        org = await self.db.get(Organization, domain.organization_id)
        return org if await self._usable(org) is not None else None

    async def _org_by_slug(self, slug: str) -> Organization | None:
        return (
            await self.db.execute(select(Organization).where(Organization.slug == slug))
        ).scalar_one_or_none()

    async def start_login(
        self,
        slug: str,
        *,
        login_hint: str | None,
        browser: str | None,
        test_ticket: str | None = None,
    ) -> LoginStart:
        org = await self._org_by_slug(slug)
        tester: PlatformUser | None = None
        if test_ticket:
            tester = await self._tester(test_ticket, org)
            conn = await self._connection_for(org, allow_inactive=True)
            login_hint = tester.email
        else:
            conn = await self._usable(org)
        if org is None or conn is None:
            raise SsoLoginError("sso_unavailable")
        purpose = "test" if tester is not None else "login"
        tester_id = tester.id if tester is not None else None
        now = _now()
        await self.db.execute(
            delete(SsoLoginRequest).where(SsoLoginRequest.expires_at < now - timedelta(hours=1))
        )
        # Reuse the browser's existing binding so two tabs logging in don't undo each other.
        browser = browser if browser and _BROWSER_RE.match(browser) else secrets.token_urlsafe(32)
        expires = now + timedelta(seconds=self.settings.sso_login_ttl_seconds)
        if conn.protocol == "saml":
            request_id = saml.new_request_id()
            assert conn.idp_sso_url and org is not None
            url = saml.authn_request_url(
                sp_entity_id=self.sp_entity_id(slug),
                acs_url=self.acs_url(slug),
                idp_sso_url=conn.idp_sso_url,
                request_id=request_id,
            )
            self.db.add(
                SsoLoginRequest(
                    id=request_id,
                    organization_id=org.id,
                    protocol="saml",
                    browser_hash=_hash(browser),
                    expires_at=expires,
                    purpose=purpose,
                    test_user_id=tester_id,
                )
            )
        else:
            discovery = await self._discovery(conn)
            state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
            verifier, challenge = oidc.pkce_pair()
            assert conn.oidc_client_id
            hint = normalize_email(login_hint) if login_hint and "@" in login_hint else None
            url = oidc.authorization_url(
                discovery,
                client_id=conn.oidc_client_id,
                redirect_uri=self.oidc_redirect_uri(slug),
                state=state,
                nonce=nonce,
                code_challenge=challenge,
                login_hint=hint,
            )
            self.db.add(
                SsoLoginRequest(
                    id=state,
                    organization_id=org.id,
                    protocol="oidc",
                    browser_hash=_hash(browser),
                    nonce=nonce,
                    code_verifier=verifier,
                    expires_at=expires,
                    purpose=purpose,
                    test_user_id=tester_id,
                )
            )
        await self.db.commit()
        return LoginStart(redirect_url=url, browser=browser)

    async def _discovery(self, conn: SsoConnection) -> oidc.Discovery:
        assert conn.oidc_discovery_url
        try:
            return await oidc.fetch_discovery(
                conn.oidc_discovery_url,
                allow_private=self.settings.sso_allow_private_idp,
                require_https=self.settings.sso_require_https,
            )
        except oidc.OidcError as exc:
            raise SsoLoginError(exc.reason) from exc

    async def _consume(
        self, org: Organization, protocol: str, request_id: str, browser: str | None
    ) -> SsoLoginRequest:
        """Claim the login state once, for this org, protocol and browser, before it expires."""
        if not request_id or not browser or len(request_id) > 64:
            raise SsoLoginError("invalid_request_state")
        claimed = (
            await self.db.execute(
                update(SsoLoginRequest)
                .where(
                    SsoLoginRequest.id == request_id,
                    SsoLoginRequest.organization_id == org.id,
                    SsoLoginRequest.protocol == protocol,
                    SsoLoginRequest.browser_hash == _hash(browser),
                    SsoLoginRequest.consumed_at.is_(None),
                    SsoLoginRequest.expires_at > _now(),
                )
                .values(consumed_at=_now())
                .returning(SsoLoginRequest)
            )
        ).scalar_one_or_none()
        if claimed is None:
            raise SsoLoginError("invalid_request_state")
        # Committed at once: whatever happens next, this state can never be used again.
        await self.db.commit()
        return claimed

    async def finish_saml(
        self, slug: str, saml_response: str, *, browser: str | None, info: RequestInfo
    ) -> SsoOutcome:
        org = await self._org_by_slug(slug)
        org_id = org.id if org is not None else None
        conn, test = await self._for_callback(org, browser)
        try:
            if org is None or conn is None or conn.protocol != "saml":
                raise SsoLoginError("sso_unavailable")
            assert conn.idp_cert_pem and conn.idp_entity_id
            try:
                identity = saml.validate_response(
                    saml_response,
                    idp_cert_pem=conn.idp_cert_pem,
                    idp_entity_id=conn.idp_entity_id,
                    sp_entity_id=self.sp_entity_id(slug),
                    acs_url=self.acs_url(slug),
                )
            except saml.SamlError as exc:
                raise SsoLoginError(exc.reason) from exc
            request = await self._consume(org, "saml", identity.in_response_to, browser)
            if request.purpose == "test":
                return await self._finish_test(
                    org, conn, request.test_user_id, identity.email, "saml", info
                )
            if not conn.active:
                raise SsoLoginError("sso_unavailable")
            return SsoOutcome(
                session=await self._sign_in(org, conn, identity.email, identity.name, "saml", info)
            )
        except SsoLoginError as exc:
            # A SAML Response that fails validation can't be trusted to say which request it
            # answers; if this browser has a test pending, the failure is that test's result.
            if test is not None and org_id is not None:
                return await self._test_failed(org_id, test, exc.reason, "saml", info)
            await self._login_failed(org_id, "saml", exc, info)
            raise

    async def finish_oidc(
        self,
        slug: str,
        *,
        state: str | None,
        code: str | None,
        error: str | None,
        browser: str | None,
        info: RequestInfo,
    ) -> SsoOutcome:
        org = await self._org_by_slug(slug)
        org_id = org.id if org is not None else None
        conn, _pending = await self._for_callback(org, browser)
        request: SsoLoginRequest | None = None
        try:
            if org is None or conn is None or conn.protocol != "oidc":
                raise SsoLoginError("sso_unavailable")
            request = await self._consume(org, "oidc", state or "", browser)
            if request.purpose != "test" and not conn.active:
                raise SsoLoginError("sso_unavailable")
            if error or not code:
                raise SsoLoginError("idp_error")
            assert conn.oidc_client_id and conn.oidc_client_secret_enc and request.nonce
            discovery = await self._discovery(conn)
            secret = crypto.decrypt(conn.oidc_client_secret_enc.decode())
            assert secret is not None and request.code_verifier
            common = {
                "allow_private": self.settings.sso_allow_private_idp,
                "require_https": self.settings.sso_require_https,
            }
            try:
                token = await oidc.exchange_code(
                    discovery,
                    code=code,
                    client_id=conn.oidc_client_id,
                    client_secret=secret,
                    redirect_uri=self.oidc_redirect_uri(slug),
                    code_verifier=request.code_verifier,
                    **common,
                )
                keys = await oidc.fetch_jwks(discovery, **common)
                identity = oidc.verify_id_token(
                    token,
                    jwks=keys,
                    issuer=discovery.issuer,
                    client_id=conn.oidc_client_id,
                    nonce=request.nonce,
                    trust_unverified_email=conn.trust_unverified_email,
                )
            except oidc.OidcError as exc:
                raise SsoLoginError(exc.reason) from exc
            if request.purpose == "test":
                return await self._finish_test(
                    org, conn, request.test_user_id, identity.email, "oidc", info
                )
            return SsoOutcome(
                session=await self._sign_in(org, conn, identity.email, identity.name, "oidc", info)
            )
        except SsoLoginError as exc:
            if request is not None and request.purpose == "test" and org_id is not None:
                return await self._test_failed(org_id, request, exc.reason, "oidc", info)
            await self._login_failed(org_id, "oidc", exc, info)
            raise

    async def _sign_in(
        self,
        org: Organization,
        conn: SsoConnection,
        email: str,
        name: str,
        protocol: str,
        info: RequestInfo,
    ) -> Session:
        email = normalize_email(email)
        verified = (
            await self.db.execute(
                select(SsoDomain).where(
                    SsoDomain.domain == email.rsplit("@", 1)[1],
                    SsoDomain.organization_id == org.id,
                    SsoDomain.verified_at.is_not(None),
                )
            )
        ).scalar_one_or_none()
        if verified is None:
            raise SsoLoginError("email_domain_not_verified", email=email)
        user = (
            await self.db.execute(select(PlatformUser).where(PlatformUser.email == email))
        ).scalar_one_or_none()
        if user is not None and user.status is not AccountStatus.active:
            raise SsoLoginError("account_suspended", email=email)
        if user is not None and user.platform_role is not PlatformRole.customer:
            raise SsoLoginError("staff_account", email=email)
        member = (
            await self.db.get(OrganizationMember, (org.id, user.id)) if user is not None else None
        )
        jit = member is None
        now_ = _now()
        if jit:
            if not conn.jit_enabled:
                raise SsoLoginError("not_provisioned", email=email)
            jit_role = OrgRole(conn.jit_role)
            try:
                await self.orgs.enforce_seat_limit(org.id, extra=1, actor_email=email)
            except AppError as exc:
                raise SsoLoginError("seat_limit", email=email) from exc
            if user is None:
                user = PlatformUser(
                    email=email,
                    name=(name or email.split("@", 1)[0])[:100],
                    password_hash=SSO_ONLY_PASSWORD_HASH,
                    platform_role=PlatformRole.customer,
                    default_organization_id=org.id,
                    email_verified_at=now_,
                )
                self.db.add(user)
                await self.db.flush()
            self.db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=jit_role))
            await self.db.flush()
            await self.orgs.ensure_personal_org(user)
            await audit_service.record(
                self.db,
                action="sso.jit_provisioned",
                actor_id=user.id,
                actor_email=user.email,
                via="sso",
                organization_id=org.id,
                target_type="user",
                target_id=user.id,
                client_ip=info.client_ip,
                request_id=info.request_id,
                detail={"protocol": protocol, "role": jit_role.value},
            )
        assert user is not None
        # The IdP vouches for the address: an account only ever signed up (never verified) is
        # taken back from whoever typed the address in first.
        reclaimed = await PlatformAuthService(self.db, self.settings).claim_by_idp(user)
        now = _now()
        user.last_login_at = now
        user.failed_logins = 0
        user.locked_until = None
        session = await PlatformAuthService(self.db, self.settings).issue_session(user, info)
        await audit_service.record(
            self.db,
            action="sso.login",
            actor_id=user.id,
            actor_email=user.email,
            via="sso",
            organization_id=org.id,
            target_type="user",
            target_id=user.id,
            client_ip=info.client_ip,
            request_id=info.request_id,
            detail={"protocol": protocol, "jit": jit, "credentials_reset": reclaimed},
        )
        await self.db.commit()
        if jit:
            from app.services.billing_service import BillingService

            await BillingService(self.db).sync_seats(org.id)
        return session

    async def _login_failed(
        self, org_id: uuid.UUID | None, protocol: str, exc: SsoLoginError, info: RequestInfo
    ) -> None:
        await self.db.rollback()
        log.info("sso_login_failed", reason=exc.reason, protocol=protocol)
        await audit_service.record(
            self.db,
            action="sso.login_failed",
            result=AuditResult.denied,
            actor_email=exc.email,
            via="sso",
            organization_id=org_id,
            client_ip=info.client_ip,
            request_id=info.request_id,
            detail={"reason": exc.reason, "protocol": protocol},
        )
        await self.db.commit()

    async def _audit(
        self,
        org: Organization,
        actor: PlatformUser,
        info: RequestInfo,
        action: str,
        *,
        result: AuditResult = AuditResult.ok,
        target_type: str = "organization",
        target_id: object = None,
        detail: dict[str, object] | None = None,
    ) -> None:
        await audit_service.record(
            self.db,
            action=action,
            result=result,
            actor_id=actor.id,
            actor_email=actor.email,
            organization_id=org.id,
            target_type=target_type,
            target_id=target_id if target_id is not None else org.id,  # type: ignore[arg-type]
            client_ip=info.client_ip,
            request_id=info.request_id,
            detail=detail,
        )
