"""Preview runtime API (B3-10).

Project routes (behind the request guard; reads = viewer, changes = editor):
  POST   /projects/{project_id}/previews                       create; token returned ONCE
  GET    /projects/{project_id}/previews                       list (no tokens)
  GET    /projects/{project_id}/previews/{preview_id}          read
  DELETE /projects/{project_id}/previews/{preview_id}          kill
  POST   /projects/{project_id}/previews/{preview_id}/rotate-token
  GET    /projects/{project_id}/generate/self-host-kit         zip: code + compose + guide

Preview routes (authenticated by the per-preview token, header X-Preview-Token, not by login):
  GET    /previews/{preview_id}/-/logs                         bounded SSE log stream, redacted
  *      /previews/{preview_id}/{path}                         request proxy to the sandboxed API
"""

import asyncio
import ipaddress
import logging
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_verified_email
from app.api.security import client_ip, current_principal
from app.config import Settings, get_settings
from app.core.ratelimit import SlidingWindowLimiter
from app.core.shared_limiter import SharedLimiter
from app.db import get_session
from app.exceptions import AppError
from app.models.preview import Preview
from app.schemas.preview import PreviewCreate, PreviewCreated, PreviewRead
from app.services import preview_runtime as rt
from app.services import preview_service as ps
from app.services.access_service import Principal
from app.services.preview_runtime import redact
from app.services.sandbox import Sandbox, SandboxError
from app.services.sandbox.docker import name_for
from app.services.self_host_kit import build_kit

project_router = APIRouter(tags=["previews"])
public_router = APIRouter(tags=["previews"])

TOKEN_HEADER = "x-preview-token"
_HOP = frozenset(
    {
        "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
        "trailers", "transfer-encoding", "upgrade", "host", "content-length",
        "content-encoding", "accept-encoding",
    }
)  # fmt: skip
# Never forwarded to the (untrusted) preview code: platform cookies and the preview token itself.
_DROP_REQUEST = _HOP | {"cookie", TOKEN_HEADER}
# A preview may not set cookies on, or run scripts against, the platform's origin.
_DROP_RESPONSE = _HOP | {
    "set-cookie", "set-cookie2", "server", "content-security-policy", "location",
    "content-location", "link", "refresh", "x-content-type-options", "cache-control",
    "x-robots-tag", "clear-site-data", "service-worker-allowed",
}  # fmt: skip
_DROP_RESPONSE_PREFIX = ("access-control-", "cross-origin-", "x-preview", "strict-transport-")
# Forced on every proxied response: an opaque origin (no cookies/storage/platform access).
PREVIEW_CSP = "sandbox allow-scripts allow-forms allow-popups"
_DOWNLOAD_TYPES = ("svg", "xml", "xhtml")  # never rendered inline from our origin
MAX_LOG_STREAMS = 2
_open_streams: dict[uuid.UUID, int] = {}
PREVIEW_HEADERS = {
    "X-Preview": "true",
    "X-Robots-Tag": "noindex, nofollow",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
}


# -- project routes -----------------------------------------------------------------------


@project_router.post(
    "/projects/{project_id}/previews",
    response_model=PreviewCreated,
    status_code=201,
    dependencies=[Depends(require_verified_email)],
)
async def create_preview(
    project_id: uuid.UUID,
    body: PreviewCreate,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> PreviewCreated:
    return await ps.PreviewService(db).create(project_id, principal.user, body.workspace_id)


@project_router.get("/projects/{project_id}/previews", response_model=list[PreviewRead])
async def list_previews(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_session)
) -> list[PreviewRead]:
    return await ps.PreviewService(db).list(project_id)


@project_router.get("/projects/{project_id}/previews/{preview_id}", response_model=PreviewRead)
async def get_preview(
    project_id: uuid.UUID, preview_id: uuid.UUID, db: AsyncSession = Depends(get_session)
) -> PreviewRead:
    return await ps.PreviewService(db).read(project_id, preview_id)


@project_router.delete("/projects/{project_id}/previews/{preview_id}", response_model=PreviewRead)
async def kill_preview(
    project_id: uuid.UUID,
    preview_id: uuid.UUID,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> PreviewRead:
    return await ps.PreviewService(db).kill(project_id, preview_id, principal.user)


@project_router.post(
    "/projects/{project_id}/previews/{preview_id}/rotate-token", response_model=PreviewCreated
)
async def rotate_preview_token(
    project_id: uuid.UUID,
    preview_id: uuid.UUID,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> PreviewCreated:
    return await ps.PreviewService(db).rotate_token(project_id, preview_id, principal.user)


@project_router.get(
    "/projects/{project_id}/generate/self-host-kit",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}}},
    dependencies=[Depends(require_verified_email)],
)
async def self_host_kit(project_id: uuid.UUID, db: AsyncSession = Depends(get_session)) -> Response:
    content, filename = await build_kit(db, project_id)
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# -- request-rate cap (per preview, per process) -------------------------------------------

_windows: dict[uuid.UUID, deque[float]] = {}


def _upstream_url(request: Request, preview_id: uuid.UUID, path: str, ip: str) -> httpx.URL:
    """The fixed host plus the caller's own path, taken from the raw (still percent-encoded)
    request line so an encoded `?`, `#` or `//` stays inside the path and cannot become a host,
    query or fragment."""
    raw = request.scope.get("raw_path")
    prefix = f"/previews/{preview_id}".encode()
    if isinstance(raw, bytes) and raw.startswith(prefix):
        rest = raw[len(prefix) :].decode("ascii")  # non-ASCII bytes -> ValueError -> 400
    else:
        rest = "/" + quote(path, safe="/")
    if rest and not rest.startswith("/"):
        raise ValueError("path must start with /")
    if "#" in rest or "?" in rest or any(ord(c) < 33 or ord(c) == 127 for c in rest):
        raise ValueError("raw path contains a query, fragment or control character")
    query = request.url.query
    if query and any(ord(c) < 33 or ord(c) == 127 for c in query):
        raise ValueError("bad query")
    return httpx.URL(f"http://{ip}:{rt.APP_PORT}{rest or '/'}" + (f"?{query}" if query else ""))


# S2-012: Docker can recycle a removed network's subnet to another tenant's preview. Before bytes
# are proxied to the stored app_ip we ask the sandbox layer which address the preview's OWN app
# container (bbsbx-<app id>, only ever created by us with the bb.sandbox label) has on the
# preview's own network. A mismatch or an unreachable runner fails closed. Positive answers are
# cached for a few seconds per preview (a recycled address can be reachable for at most that long).
VERIFY_TTL_SECONDS = 5.0
_verified: dict[uuid.UUID, tuple[str, float]] = {}


async def verify_upstream(box: Sandbox, p: Preview, now: float | None = None) -> None:
    ip = p.app_ip or ""
    t = time.monotonic() if now is None else now
    hit = _verified.get(p.id)
    if hit is not None and hit[0] == ip and t - hit[1] < VERIFY_TTL_SECONDS:
        return
    try:
        actual = await box.ip_of(p.app_sandbox, name_for(p.db_sandbox))
    except (SandboxError, OSError, TimeoutError):
        actual = None
    if not ip or actual != ip:
        _verified.pop(p.id, None)
        await ps.sleep_preview(p.id, "address no longer matches its container; restarted")
        raise AppError(
            "preview_unverified", "the preview could not be verified; retry", 502,
            headers={"Retry-After": "3"},
        )  # fmt: skip
    _verified[p.id] = (ip, t)


def rate_check(preview_id: uuid.UUID, per_minute: int, now: float | None = None) -> int | None:
    """None = allowed; else seconds until a slot frees up. Sliding 60 s window."""
    t = time.monotonic() if now is None else now
    q = _windows.setdefault(preview_id, deque())
    while q and q[0] <= t - 60:
        q.popleft()
    if len(q) >= per_minute:
        return max(1, int(q[0] + 60 - t) + 1)
    q.append(t)
    return None


async def _read_body(request: Request, cap: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > cap:
        raise AppError("body_too_large", "request body is too large for a preview", 413)
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > cap:
            raise AppError("body_too_large", "request body is too large for a preview", 413)
    return bytes(buf)


_ip_limiter: SlidingWindowLimiter | None = None
_shared = SharedLimiter(lambda: ps.session_factory())  # lazily: tests swap the factory


log = logging.getLogger(__name__)
_proxy_warned = False


def _warn_shared_proxy_bucket(ip: str, settings: Settings) -> None:
    """S-4: untrusted forwarded headers + a loopback/private peer means a reverse proxy: every visitor
    then shares this one bucket. The key stays the peer address (an untrusted header must never pick
    the bucket); per-visitor keys only happen with trust_proxy_headers=true. Warn once."""
    global _proxy_warned  # noqa: PLW0603
    if _proxy_warned or settings.trust_proxy_headers:
        return
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return
    if addr.is_loopback or addr.is_private:
        _proxy_warned = True
        log.warning(
            "preview_ip_bucket_shared: peer %s is a loopback/private address and trust_proxy_headers is "
            "false; all visitors share one pre-auth rate bucket. Set BUILDER_TRUST_PROXY_HEADERS=true "
            "if a reverse proxy sets X-Forwarded-For.", ip,
        )  # fmt: skip


def _pre_auth_ip_check(request: Request, settings: Settings) -> None:
    """S2-005: cheap per-address limit BEFORE the lazy sweep, the token lookup or any query, so
    unauthenticated floods cost a dict lookup, not database work. In process on purpose."""
    global _ip_limiter  # noqa: PLW0603
    limit = settings.preview_ip_rate_per_minute
    if _ip_limiter is None or _ip_limiter.attempts != limit:
        _ip_limiter = SlidingWindowLimiter(attempts=limit, window_seconds=60)
    ip = client_ip(request, settings) or "unknown"
    _warn_shared_proxy_bucket(ip, settings)
    if not _ip_limiter.allow(ip):
        raise AppError(
            "rate_limited", "too many requests", 429,
            headers={"Retry-After": str(_ip_limiter.retry_after(ip))},
        )  # fmt: skip


async def _gate(preview_id: uuid.UUID, request: Request) -> Preview:
    """Token, state, kill switch and rate cap: everything before any bytes reach the sandbox."""
    _pre_auth_ip_check(request, get_settings())
    ps.maybe_sweep()  # expiry / kill switch act even when the scheduler is off
    p = await ps.authenticate(preview_id, request.headers.get(TOKEN_HEADER))
    if p.state in ("expired", "killed", "failed"):
        raise AppError("preview_gone", f"this preview is {p.state}", 410)
    await ps.ensure_enabled(p.project_id)
    per_minute = int(p.limits.get("rate_per_minute", 300))  # type: ignore[call-overload]
    wait = rate_check(p.id, per_minute)  # in-process first check
    if wait is None:  # S2-005: the count every worker shares
        wait = await _shared.hit(f"preview:{p.id}", per_minute, 60)
    if wait is not None:
        raise AppError(
            "rate_limited", "too many requests to this preview", 429, headers={"Retry-After": str(wait)}
        )
    return p


@public_router.get("/previews/{preview_id}/-/logs")
async def preview_logs(preview_id: uuid.UUID, request: Request) -> StreamingResponse:
    settings = get_settings()
    p = await _gate(preview_id, request)  # token, state, kill switch, org switch, rate cap
    if _open_streams.get(p.id, 0) >= MAX_LOG_STREAMS:
        raise AppError("too_many_streams", "too many open log streams for this preview", 429)
    _open_streams[p.id] = _open_streams.get(p.id, 0) + 1
    box = ps.get_sandbox(settings)

    async def stream() -> AsyncIterator[str]:
        try:
            async for chunk in _stream_logs(request, box, preview_id, settings):
                yield chunk
        finally:
            _open_streams[p.id] = max(0, _open_streams.get(p.id, 1) - 1)

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={**PREVIEW_HEADERS, "X-Preview-Id": str(p.id)},
    )  # fmt: skip


async def _stream_logs(
    request: Request, box: Sandbox, preview_id: uuid.UUID, settings: Settings
) -> AsyncIterator[str]:
    yield "event: info\ndata: preview logs (credentials are redacted)\n\n"
    deadline = time.monotonic() + settings.preview_log_stream_max_seconds
    budget = 256 * 1024
    since: str | None = None
    while time.monotonic() < deadline and budget > 0:
        cur = await ps._load(preview_id)
        if cur is None or cur.state in ("expired", "killed", "failed"):
            break
        try:
            await ps.ensure_enabled(cur.project_id)  # kill switch mid-stream ends it
        except AppError:
            yield "event: end\ndata: previews are switched off\n\n"
            return
        polled = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        if cur.state == "running":
            text = await box.logs(cur.app_sandbox, tail=200, since=since)
            for line in redact(text).splitlines():
                line = line[:2000]
                budget -= len(line) + 8
                yield f"data: {line}\n\n"
                if budget <= 0:
                    break
            since = polled
        else:
            yield f"event: state\ndata: {cur.state}\n\n"
        if await request.is_disconnected():
            return
        await asyncio.sleep(1.0)
    yield "event: end\ndata: log stream closed\n\n"


@public_router.api_route(
    "/previews/{preview_id}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
@public_router.api_route(
    "/previews/{preview_id}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
async def proxy(preview_id: uuid.UUID, request: Request, path: str = "") -> Response:
    settings = get_settings()
    p = await _gate(preview_id, request)
    body = await _read_body(request, settings.preview_max_body_bytes)
    p = await ps.ensure_running(p.id, settings.preview_wake_timeout_seconds)
    await verify_upstream(ps.get_sandbox(settings), p)
    await ps.touch(p.id)
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP_REQUEST}
    headers["accept-encoding"] = "identity"
    try:
        url = _upstream_url(request, p.id, path, p.app_ip or "")
    except (httpx.InvalidURL, ValueError):
        raise AppError("bad_path", "that request path is not valid", 400) from None
    cap = settings.preview_max_response_bytes
    chunks: list[bytes] = []
    size = 0
    try:
        async with httpx.AsyncClient(
            timeout=settings.preview_request_timeout_seconds, trust_env=False, follow_redirects=False
        ) as client:
            async with asyncio.timeout(settings.preview_request_timeout_seconds):
                async with client.stream(request.method, url, headers=headers, content=body) as up:
                    async for chunk in up.aiter_bytes():
                        size += len(chunk)
                        if size > cap:
                            raise AppError(
                                "response_too_large", "the preview response is too large", 502
                            )
                        chunks.append(chunk)
                    status, up_headers = up.status_code, up.headers
    except (httpx.ConnectError, httpx.RemoteProtocolError, ConnectionError):
        await ps.sleep_preview(p.id, "stopped unexpectedly; restarted")
        raise AppError(
            "preview_restarting", "the preview stopped and will restart; retry", 503,
            headers={"Retry-After": "3"},
        ) from None  # fmt: skip
    except (httpx.TimeoutException, TimeoutError):
        raise AppError("preview_timeout", "the preview did not answer in time", 504) from None
    out = {
        k: v
        for k, v in up_headers.multi_items()
        if k.lower() not in _DROP_RESPONSE and not k.lower().startswith(_DROP_RESPONSE_PREFIX)
    }
    out.update(PREVIEW_HEADERS)
    out["X-Preview-Id"] = str(p.id)
    # Untrusted output served from the platform host: always an opaque origin, never sniffed,
    # and image/xml-like documents are downloads, not pages.
    out["Content-Security-Policy"] = PREVIEW_CSP
    ctype = up_headers.get("content-type", "").lower()
    if any(t in ctype for t in _DOWNLOAD_TYPES):
        out["Content-Disposition"] = "attachment"
    return Response(content=b"".join(chunks), status_code=status, headers=out)
