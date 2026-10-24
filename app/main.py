import logging
import os
import re
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api import (
    account,
    admin,
    auth,
    authorization,
    deployment,
    documents,
    entities,
    fields,
    generate,
    health,
    keycloak,
    members,
    observability,
    payments,
    projects,
    relations,
    spec,
    storage,
)
from app.api.security import guard
from app.config import Settings, get_settings
from app.core.platform_security import check_secret_strength
from app.db import get_session_factory
from app.errors import register_exception_handlers
from app.exceptions import AppError
from app.services.platform_auth_service import PlatformAuthService

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

        declared = headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await self._too_large(send, request_id)
            return

        received = 0
        too_large = False

        async def limited_receive() -> Message:
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
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
            structlog.contextvars.unbind_contextvars("request_id")
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
    async with get_session_factory()() as session:
        try:
            admin_user = await PlatformAuthService(session, settings).bootstrap_admin()
        except AppError as exc:
            raise RuntimeError(f"BUILDER_BOOTSTRAP_ADMIN_* is invalid: {exc.message}") from exc
        if admin_user is not None:
            log.info("bootstrap_admin_created", email=admin_user.email)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Backend Builder",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With", "X-Request-ID"],
        expose_headers=["Content-Disposition", "X-Generation-Id", "X-Spec-Hash", "X-Request-ID"],
    )
    app.add_middleware(SecurityMiddleware, settings=settings)
    register_exception_handlers(app)

    # Open on purpose: liveness, and the sign-in endpoints (which carry their own protections).
    app.include_router(health.router)
    app.include_router(account.router)
    app.include_router(admin.router)

    # Everything else sits behind the request guard (authentication + project membership).
    guarded = [Depends(guard)]
    for router in (
        auth.router,
        authorization.router,
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
        generate.router,
    ):
        app.include_router(router, dependencies=guarded)
    return app


app = create_app()
