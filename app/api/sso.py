"""Enterprise SSO routes (PLATFORM_SAAS_PLAN §4.2, §12.D).

Public (the browser and the IdP call these; no session exists yet):
    GET  /sso/metadata/{slug}          SAML SP metadata for the org's IdP
    GET  /sso/{slug}/login             start: 302 to the IdP, binding cookie set
    POST /sso/saml/{slug}/acs          SAML HTTP-POST binding (the IdP posts the Response)
    GET  /sso/oidc/{slug}/callback     OIDC authorization-code redirect
The sign-in endpoints always answer with a redirect to the app: `#/sso/complete` with the
refresh cookie set (the app then calls /account/refresh as after any reload), or
`#/login?sso_error=<reason>`. They never show an error page from here.

Org admins (session only, never an API token):
    GET    /orgs/{slug}/sso                         configuration + SP details + domains
    PUT    /orgs/{slug}/sso                         save SAML or OIDC configuration
    DELETE /orgs/{slug}/sso                         remove the configuration
    POST   /orgs/{slug}/sso/activate                turn SSO on (needs a verified domain)
    POST   /orgs/{slug}/sso/deactivate              turn SSO off
    POST   /orgs/{slug}/sso/domains                 claim a domain (returns the TXT record)
    POST   /orgs/{slug}/sso/domains/{domain}/verify check DNS
    DELETE /orgs/{slug}/sso/domains/{domain}        release a domain
    POST   /orgs/{slug}/sso/test                    "test with my own e-mail": a login URL that
                                                    ends at #/org/<slug>/sso?sso_test=<result>
    POST   /orgs/{slug}/sso/check                   check the config without signing in
"""

import urllib.parse

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.account import APP_COOKIE, APP_COOKIE_PATH, set_refresh_cookie
from app.api.security import OrgContext, forbidden, org_context, rate_limit_auth, request_info
from app.config import Settings, get_settings
from app.db import get_session
from app.exceptions import AppError
from app.models.enums import OrgKind
from app.models.platform import Organization, PlatformUser
from app.models.sso import SsoDomain
from app.schemas.sso import (
    SsoCertificateRead,
    SsoCheckItemRead,
    SsoCheckRead,
    SsoConfigRead,
    SsoConfigUpdate,
    SsoDomainCreate,
    SsoDomainRead,
    SsoServiceProviderRead,
    SsoTestRead,
    SsoTestStart,
)
from app.services import saml
from app.services.platform_auth_service import Session
from app.services.sso_service import (
    BROWSER_COOKIE,
    TEST_TICKET_SECONDS,
    SsoCheck,
    SsoLoginError,
    SsoOutcome,
    SsoService,
)

public_router = APIRouter(prefix="/sso", tags=["sso"])
org_router = APIRouter(prefix="/orgs", tags=["sso"])

SLUG = Path(min_length=1, max_length=100)
DOMAIN = Path(min_length=1, max_length=260)
COOKIE_PATH = "/sso"


# -- helpers ---------------------------------------------------------------------------------


def _set_browser_cookie(response: Response, value: str, settings: Settings) -> None:
    # The SAML Response arrives as a cross-site POST from the IdP: only SameSite=None cookies
    # travel with it, and those must be Secure (browsers accept that on http://localhost).
    response.set_cookie(
        BROWSER_COOKIE,
        value,
        max_age=settings.sso_login_ttl_seconds,
        path=COOKIE_PATH,
        httponly=True,
        secure=True,
        samesite="none",
    )


def _clear_browser_cookie(response: Response) -> None:
    response.delete_cookie(
        BROWSER_COOKIE, path=COOKIE_PATH, httponly=True, secure=True, samesite="none"
    )


def _redirect(url: str) -> RedirectResponse:
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _failed(service: SsoService, reason: str) -> RedirectResponse:
    response = _redirect(service.app_url("login?" + urllib.parse.urlencode({"sso_error": reason})))
    _clear_browser_cookie(response)
    return response


def _finished(
    service: SsoService, slug: str, outcome: SsoOutcome, settings: Settings
) -> RedirectResponse:
    if outcome.test_result is not None:
        query = urllib.parse.urlencode({"sso_test": outcome.test_result})
        response = _redirect(service.app_url(f"org/{slug}/sso?{query}"))
        _clear_browser_cookie(response)
        return response
    assert outcome.session is not None
    return _signed_in(service, outcome.session, settings)


def _signed_in(service: SsoService, session: Session, settings: Settings) -> RedirectResponse:
    response = _redirect(service.app_url("sso/complete"))
    set_refresh_cookie(
        response,
        APP_COOKIE,
        APP_COOKIE_PATH,
        session.refresh_token,
        session.refresh_max_age,
        settings,
    )
    _clear_browser_cookie(response)
    return response


def _session_only(ctx: OrgContext) -> None:
    if ctx.principal.via != "session":
        raise forbidden(
            "SSO settings need a signed-in session, not an API token", "session_required"
        )


async def _config_read(service: SsoService, org: Organization) -> SsoConfigRead:
    conn = await service.connection(org.id)
    domains = await service.domains(org.id)
    sp = SsoServiceProviderRead(
        entity_id=service.sp_entity_id(org.slug),
        acs_url=service.acs_url(org.slug),
        metadata_url=service.sp_entity_id(org.slug),
        oidc_redirect_uri=service.oidc_redirect_uri(org.slug),
        login_url=service.login_url(org.slug),
    )
    domain_rows = []
    for d in domains:
        name, value = service.dns_record(d)
        domain_rows.append(
            SsoDomainRead(
                domain=d.domain,
                verified_at=d.verified_at,
                created_at=d.created_at,
                dns_record_name=name,
                dns_record_value=value,
            )
        )
    allowed = await service.allowed_by_plan(org.id)
    last_test = None
    if conn is not None and conn.last_test_at is not None and conn.last_test_result:
        tester = (
            await service.db.get(PlatformUser, conn.last_tested_by) if conn.last_tested_by else None
        )
        last_test = SsoTestRead(
            at=conn.last_test_at,
            result=conn.last_test_result,
            tested_by_email=tester.email if tester else None,
        )
    if conn is None:
        return SsoConfigRead(configured=False, allowed_by_plan=allowed, sp=sp, domains=domain_rows)
    return SsoConfigRead(
        configured=True,
        allowed_by_plan=allowed,
        protocol=conn.protocol,
        active=conn.active,
        idp_entity_id=conn.idp_entity_id,
        idp_sso_url=conn.idp_sso_url,
        idp_certificate=(
            SsoCertificateRead(**saml.cert_summary(conn.idp_cert_pem))
            if conn.idp_cert_pem
            else None
        ),
        oidc_discovery_url=conn.oidc_discovery_url,
        oidc_client_id=conn.oidc_client_id,
        oidc_client_secret_set=conn.oidc_client_secret_enc is not None,
        jit_enabled=conn.jit_enabled,
        jit_role=conn.jit_role,
        trust_unverified_email=conn.trust_unverified_email,
        updated_at=conn.updated_at,
        last_test=last_test,
        sp=sp,
        domains=domain_rows,
    )


def _domain_read(service: SsoService, d: SsoDomain) -> SsoDomainRead:
    name, value = service.dns_record(d)
    return SsoDomainRead(
        domain=d.domain,
        verified_at=d.verified_at,
        created_at=d.created_at,
        dns_record_name=name,
        dns_record_value=value,
    )


# -- public: metadata + sign-in ---------------------------------------------------------------


@public_router.get("/metadata/{slug}", response_class=Response)
async def sp_metadata(
    slug: str = SLUG,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    org = (
        await db.execute(
            select(Organization).where(
                Organization.slug == slug,
                Organization.kind == OrgKind.team,
                Organization.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if org is None:
        raise AppError(code="not_found", message="not found", status_code=404)
    service = SsoService(db, settings)
    xml = saml.sp_metadata(sp_entity_id=service.sp_entity_id(slug), acs_url=service.acs_url(slug))
    return Response(content=xml, media_type="application/samlmetadata+xml")


@public_router.get(
    "/{slug}/login", response_class=RedirectResponse, dependencies=[Depends(rate_limit_auth)]
)
async def start_login(
    request: Request,
    slug: str = SLUG,
    login_hint: str | None = Query(default=None, max_length=254),
    test: str | None = Query(default=None, max_length=2048),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    service = SsoService(db, settings)
    try:
        start = await service.start_login(
            slug,
            login_hint=login_hint,
            browser=request.cookies.get(BROWSER_COOKIE),
            test_ticket=test,
        )
    except SsoLoginError as exc:
        return _failed(service, exc.reason)
    response = _redirect(start.redirect_url)
    _set_browser_cookie(response, start.browser, settings)
    return response


@public_router.post(
    "/saml/{slug}/acs", response_class=RedirectResponse, dependencies=[Depends(rate_limit_auth)]
)
async def saml_acs(
    request: Request,
    slug: str = SLUG,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """The IdP's HTTP-POST binding. Parsed by hand: a form body is all it ever is."""
    service = SsoService(db, settings)
    body = await request.body()
    try:
        form = urllib.parse.parse_qs(body.decode("ascii"), max_num_fields=10, strict_parsing=True)
    except (UnicodeDecodeError, ValueError):
        form = {}
    saml_response = (form.get("SAMLResponse") or [""])[0]
    if not saml_response:
        return _failed(service, "malformed")
    try:
        outcome = await service.finish_saml(
            slug,
            saml_response,
            browser=request.cookies.get(BROWSER_COOKIE),
            info=request_info(request),
        )
    except SsoLoginError as exc:
        return _failed(service, exc.reason)
    return _finished(service, slug, outcome, settings)


@public_router.get(
    "/oidc/{slug}/callback",
    response_class=RedirectResponse,
    dependencies=[Depends(rate_limit_auth)],
)
async def oidc_callback(
    request: Request,
    slug: str = SLUG,
    state: str | None = Query(default=None, max_length=128),
    code: str | None = Query(default=None, max_length=4096),
    error: str | None = Query(default=None, max_length=200),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    service = SsoService(db, settings)
    try:
        outcome = await service.finish_oidc(
            slug,
            state=state,
            code=code,
            error=error,
            browser=request.cookies.get(BROWSER_COOKIE),
            info=request_info(request),
        )
    except SsoLoginError as exc:
        return _failed(service, exc.reason)
    return _finished(service, slug, outcome, settings)


# -- org admins: configuration ---------------------------------------------------------------


@org_router.get("/{slug}/sso", response_model=SsoConfigRead)
async def get_sso(
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SsoConfigRead:
    return await _config_read(SsoService(db, settings), ctx.org)


@org_router.put("/{slug}/sso", response_model=SsoConfigRead)
async def put_sso(
    body: SsoConfigUpdate,
    request: Request,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SsoConfigRead:
    _session_only(ctx)
    service = SsoService(db, settings)
    org = ctx.org
    await service.save_config(org, body, ctx.principal.user, request_info(request))
    return await _config_read(service, org)


@org_router.delete("/{slug}/sso", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sso(
    request: Request,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> None:
    _session_only(ctx)
    await SsoService(db, settings).delete_config(ctx.org, ctx.principal.user, request_info(request))


async def _toggle(
    active: bool, request: Request, ctx: OrgContext, db: AsyncSession, settings: Settings
) -> SsoConfigRead:
    _session_only(ctx)
    service = SsoService(db, settings)
    org = ctx.org
    await service.set_active(org, active, ctx.principal.user, request_info(request))
    return await _config_read(service, org)


@org_router.post("/{slug}/sso/activate", response_model=SsoConfigRead)
async def activate_sso(
    request: Request,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SsoConfigRead:
    return await _toggle(True, request, ctx, db, settings)


@org_router.post("/{slug}/sso/deactivate", response_model=SsoConfigRead)
async def deactivate_sso(
    request: Request,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SsoConfigRead:
    return await _toggle(False, request, ctx, db, settings)


@org_router.post(
    "/{slug}/sso/domains", response_model=SsoDomainRead, status_code=status.HTTP_201_CREATED
)
async def add_domain(
    body: SsoDomainCreate,
    request: Request,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SsoDomainRead:
    _session_only(ctx)
    service = SsoService(db, settings)
    row = await service.add_domain(ctx.org, body.domain, ctx.principal.user, request_info(request))
    return _domain_read(service, row)


@org_router.post("/{slug}/sso/domains/{domain}/verify", response_model=SsoDomainRead)
async def verify_domain(
    request: Request,
    domain: str = DOMAIN,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SsoDomainRead:
    _session_only(ctx)
    service = SsoService(db, settings)
    row = await service.verify_domain(ctx.org, domain, ctx.principal.user, request_info(request))
    return _domain_read(service, row)


@org_router.delete("/{slug}/sso/domains/{domain}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_domain(
    request: Request,
    domain: str = DOMAIN,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> None:
    _session_only(ctx)
    await SsoService(db, settings).remove_domain(
        ctx.org, domain, ctx.principal.user, request_info(request)
    )


# -- org admins: test and check (§12.D.5–6) --------------------------------------------------


def check_read(result: SsoCheck) -> SsoCheckRead:
    return SsoCheckRead(
        ok=result.ok,
        protocol=result.protocol,
        active=result.active,
        checks=[
            SsoCheckItemRead(name=i.name, status=i.status, detail=i.detail)  # type: ignore[arg-type]
            for i in result.items
        ],
    )


@org_router.post("/{slug}/sso/test", response_model=SsoTestStart)
async def start_sso_test(
    request: Request,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SsoTestStart:
    """ "Test with my own e-mail": sign in at the IdP as yourself; the result is recorded and
    shown here. Works while SSO is still switched off, and never signs anyone in."""
    _session_only(ctx)
    url = await SsoService(db, settings).create_test(
        ctx.org, ctx.principal.user, request_info(request)
    )
    return SsoTestStart(login_url=url, expires_in=TEST_TICKET_SECONDS)


@org_router.post("/{slug}/sso/check", response_model=SsoCheckRead)
async def check_sso(
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SsoCheckRead:
    """What would stop SSO working (plan, domain, certificate expiry, OIDC discovery/JWKS)."""
    return check_read(await SsoService(db, settings).check(ctx.org))
