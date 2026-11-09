import asyncio
import logging
import os
import re
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api import (
    account,
    admin,
    admin_previews,
    advisor,
    agent_approvals,
    agent_runs,
    ai_registry,
    auth,
    authorization,
    behavior,
    billing,
    data_import,
    dependencies,
    deployment,
    documents,
    entities,
    fields,
    generate,
    health,
    impersonation,
    keycloak,
    members,
    migration_plan,
    observability,
    orgs,
    payments,
    previews,
    projects,
    relations,
    requirements,
    scim,
    spec,
    spec_ops,
    sso,
    status,
    storage,
    usage,
    wellknown,
    workspaces,
)
from app.api.body_limit import INTAKE_MAX_BYTES, SpecWriteLimit, is_intake
from app.api.input_guard import reject_nul_characters
from app.api.security import guard
from app.config import Settings, get_settings
from app.core import rls
from app.core.platform_security import check_secret_strength
from app.db import get_session_factory
from app.errors import register_exception_handlers
from app.exceptions import AppError
from app.services.platform_auth_service import PlatformAuthService
from app.services.scim_protocol import ScimError

log = structlog.get_logger()

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


def configure_logging(log_level: str) -> None:
    logging.basicConfig(level=log_level, format="%(message)s")
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(log_level)),
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
    )


class SecurityMiddleware:
    """Request id, body size cap and safe response headers, for every request.

    Pure ASGI (no BaseHTTPMiddleware) so streaming downloads are not buffered.
    """

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.max_bytes = settings.max_request_bytes
        self.hsts = not settings.is_local

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        incoming = headers.get("x-request-id", "")
        request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)

        # Requirements intake is allowed 12 MB of files (SpecWriteLimit enforces its own 13 MB cap).
        max_bytes = (
            max(self.max_bytes, INTAKE_MAX_BYTES)
            if is_intake(scope["method"], scope.get("path", ""))
            else self.max_bytes
        )
        declared = headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > max_bytes:
            await self._too_large(send, request_id)
            return

        received = 0
        too_large = False

        async def limited_receive() -> Message:
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > max_bytes:
                    too_large = True
                    return {"type": "http.disconnect"}
            return message

        path = scope.get("path", "")
        is_doc = path in _DOC_PATHS or path.startswith("/docs/")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                extra = [
                    (b"x-request-id", request_id.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"cross-origin-opener-policy", b"same-origin"),
                ]
                names = {k.lower() for k, _ in message.get("headers", [])}
                if b"cache-control" not in names:
                    extra.append((b"cache-control", b"no-store"))
                if not is_doc:
                    extra.append(
                        (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'")
                    )
                if self.hsts:
                    extra.append(
                        (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
                    )
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        try:
            await self.app(scope, limited_receive, send_with_headers)
        finally:
            structlog.contextvars.unbind_contextvars("request_id", "organization_id")
            rls.clear()
        if too_large:
            log.warning("request_body_too_large", limit=self.max_bytes)

    async def _too_large(self, send: Send, request_id: str) -> None:
        body = b'{"code":"payload_too_large","message":"request body is too large","details":[]}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"x-request-id", request_id.encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def check_startup(settings: Settings) -> None:
    """Refuse to start with a configuration that would silently weaken security."""
    if "*" in settings.cors_origins:
        raise RuntimeError(
            "BUILDER_CORS_ORIGINS must list explicit origins, not '*' (cookies are used)"
        )
    if not os.environ.get("SECRET_KEY") and settings.is_local:
        # Local convenience only: a throwaway key means sessions end on restart.
        os.environ["SECRET_KEY"] = secrets.token_urlsafe(48)
        log.warning(
            "secret_key_generated", detail="SECRET_KEY unset; using a temporary key (local only)"
        )
    if settings.key_provider != "env":  # fail early on a bad key file/command, never at first use
        from app.core import crypto

        crypto.reset()
        crypto.active_key_id()
    problem = check_secret_strength(os.environ.get("SECRET_KEY", ""), settings.environment)
    if problem:
        raise RuntimeError(problem)
    if (
        not settings.is_local
        and settings.signup_mode == "open"
        and not settings.bootstrap_admin_email
    ):
        log.warning(
            "open_signup_without_admin",
            detail="sign-up is open and BUILDER_BOOTSTRAP_ADMIN_EMAIL is unset: no admin console",
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    check_startup(settings)
    from app.core.production_checks import check_production_ready

    check_production_ready(settings)
    from app.core import rls as _rls

    reason = _rls.startup_problem(settings)
    if reason:
        raise RuntimeError(reason)
    if settings.rls_enabled:
        from app.db import get_engine

        await _rls.assert_role_enforces_rls(get_engine())
    async with get_session_factory()() as session:
        try:
            admin_user = await PlatformAuthService(session, settings).bootstrap_admin()
        except AppError as exc:
            raise RuntimeError(f"BUILDER_BOOTSTRAP_ADMIN_* is invalid: {exc.message}") from exc
        if admin_user is not None:
            log.info("bootstrap_admin_created", email=admin_user.email)
    try:  # S2-007: free spend holds a dead process left behind (never blocks startup)
        from app.services.ai.platform_cap import PlatformCap

        async with get_session_factory()() as session:
            freed = await PlatformCap(session, settings).reap_expired()
        if freed:
            log.info("ai_reservations_reaped", micro_usd=freed)
        async with get_session_factory()() as session:
            warning = await PlatformCap(session, settings).unbounded_key_warning()
        if warning:
            log.warning("ai_console_key_unbounded", detail=warning)
    except Exception as exc:  # noqa: BLE001
        log.warning("ai_reservation_reap_failed", error=type(exc).__name__)
    scheduler: asyncio.Task[None] | None = None
    if settings.preview_scheduler_enabled:
        from app.services import preview_service

        scheduler = asyncio.create_task(
            preview_service.scheduler_loop(settings.preview_sweep_interval_seconds)
        )
    sweeper: asyncio.Task[None] | None = None
    if settings.agent_sweeper_enabled and settings.environment != "test":  # B-003: crash-resume
        from app.services.agent.sweeper import sweeper_loop

        sweeper = asyncio.create_task(sweeper_loop(settings))
    try:
        async with _mcp_lifespan(app):
            yield
    finally:
        for task in (scheduler, sweeper):
            if task is not None:
                task.cancel()


@asynccontextmanager
async def _mcp_lifespan(app: FastAPI) -> AsyncIterator[None]:
    # The MCP sub-app has its own lifespan that starts the Streamable-HTTP session
    # manager's task group. A mounted Starlette app's lifespan is NOT run automatically,
    # so we drive it here. Without this, every /mcp request raises
    # "Task group is not initialized".
    mcp_app = getattr(app.state, "mcp_app", None)
    if mcp_app is not None:
        async with mcp_app.router.lifespan_context(mcp_app):
            yield
    else:
        yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    from app.services.agent.run_service import configure_agent_deps
    from app.services.agent.wiring import default_deps

    configure_agent_deps(default_deps())

    app = FastAPI(
        title="Backend Builder",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        dependencies=[Depends(reject_nul_characters)],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With", "X-Request-ID", "X-Preview-Token"],
        expose_headers=["Content-Disposition", "X-Generation-Id", "X-Spec-Hash", "X-Request-ID", "X-Preview-Token"],
    )
    app.add_middleware(SpecWriteLimit, max_bytes=settings.max_spec_write_bytes)
    app.add_middleware(SecurityMiddleware, settings=settings)
    register_exception_handlers(app)

    @app.exception_handler(ScimError)
    async def handle_scim_error(request: Request, exc: ScimError) -> Response:
        return scim.scim_error_response(exc)

    # Open on purpose: liveness, and the sign-in endpoints (which carry their own protections).
    app.include_router(health.router)
    app.include_router(account.router)
    app.include_router(impersonation.router)  # "view as" banner, writes switch, end
    app.include_router(admin.router)
    app.include_router(admin_previews.router)  # preview limits: require_admin
    app.include_router(previews.public_router)  # preview proxy/logs: per-preview token
    app.include_router(orgs.router)  # organization routes authenticate via current_principal
    app.include_router(wellknown.router)  # RFC 9728 discovery, no auth
    app.include_router(billing.router)  # Stripe webhook: authenticated by its signature
    app.include_router(sso.public_router)  # SSO sign-in: the IdP's signature + one-time state
    app.include_router(sso.org_router)  # SSO settings: org_context like every /orgs route
    app.include_router(scim.router)  # SCIM 2.0: authenticated by the org's SCIM bearer token
    app.include_router(scim.org_router)  # SCIM settings: org_context like every /orgs route
    app.include_router(ai_registry.org_router)  # AI cost/settings, org registry: org_context
    app.include_router(usage.org_router)  # usage metering: org_context

    # Everything else sits behind the request guard (authentication + project membership).
    guarded = [Depends(guard)]
    for router in (
        auth.router,
        authorization.router,
        behavior.router,
        observability.router,
        deployment.router,
        documents.router,
        keycloak.router,
        payments.router,
        storage.router,
        projects.router,
        members.router,
        entities.router,
        fields.router,
        relations.router,
        spec.router,
        advisor.router,
        spec_ops.router,
        status.router,
        generate.router,
        migration_plan.router,
        ai_registry.router,
        workspaces.router,
        agent_runs.router,
        agent_approvals.router,
        requirements.router,
        data_import.router,
        dependencies.router,
        previews.project_router,
    ):
        app.include_router(router, dependencies=guarded)

    # MCP server (Streamable HTTP, own auth middleware, NOT behind the REST guard).
    from app.api.mcp import build_mcp_app
    from app.db import get_session_factory as _gsf

    mcp_starlette = build_mcp_app(_gsf())
    app.state.mcp_app = mcp_starlette
    app.mount("/mcp", mcp_starlette)

    return app


app = create_app()
