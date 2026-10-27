"""SCIM 2.0 routes (PLATFORM_SAAS_PLAN §4.3, §12.E).

The IdP (bearer = the org's SCIM token; the org comes from the token, never from the URL):
    GET    /scim/v2/ServiceProviderConfig
    GET    /scim/v2/ResourceTypes[/{id}]      GET /scim/v2/Schemas[/{id}]
    GET    /scim/v2/Users?filter=userName eq "…"&startIndex=&count=
    POST   /scim/v2/Users                     GET | PUT | PATCH | DELETE /scim/v2/Users/{id}
    GET    /scim/v2/Groups?filter=displayName eq "…"&excludedAttributes=members
    POST   /scim/v2/Groups                    GET | PUT | PATCH | DELETE /scim/v2/Groups/{id}
Bodies and answers are `application/scim+json`; errors use the SCIM error schema.

Org admins (session only, never an API token):
    GET    /orgs/{slug}/scim          status, base URL, token hint, groups, dictionary
    POST   /orgs/{slug}/scim/token    create the directory or rotate its token (shown once)
    PATCH  /orgs/{slug}/scim          {active?, group_roles?}  (mapping to owner: owners only)
    DELETE /orgs/{slug}/scim          remove the directory (memberships stay)
"""

import json
from typing import Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.security import (
    OrgContext,
    auth_limiter,
    client_ip,
    forbidden,
    org_context,
    request_info,
)
from app.config import Settings, get_settings
from app.db import get_session
from app.schemas.scim import ScimConfigRead, ScimConfigUpdate, ScimGroupSummary, ScimTokenRead
from app.services import scim_protocol as proto
from app.services.scim_protocol import ScimError
from app.services.scim_service import ScimContext, ScimService

router = APIRouter(prefix="/scim/v2", tags=["scim"])
org_router = APIRouter(prefix="/orgs", tags=["scim"])

MAX_BODY = 1_000_000


def scim_response(content: object, status_code: int = 200, **headers: str) -> JSONResponse:
    return JSONResponse(
        content=content, status_code=status_code, media_type=proto.MEDIA_TYPE, headers=headers
    )


def scim_error_response(exc: ScimError) -> JSONResponse:
    headers = {"WWW-Authenticate": 'Bearer realm="scim"'} if exc.status == 401 else {}
    return scim_response(exc.body(), exc.status, **headers)


# -- authentication -------------------------------------------------------------------------


async def scim_auth(
    request: Request,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ScimContext:
    """The bearer names the directory, and so the org. Failed attempts count against the same
    per-address limiter as sign-ins."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    ip = client_ip(request) or "unknown"
    if auth_limiter().blocked(ip):
        raise ScimError(429, "too many failed attempts; wait a few minutes")
    try:
        ctx = await ScimService(db, settings).authenticate(
            token.strip() if scheme.lower() == "bearer" else None, request_info(request)
        )
    except ScimError as exc:
        if exc.status == 401 and not auth_limiter().allow(ip):
            raise ScimError(429, "too many failed attempts; wait a few minutes") from exc
        raise
    request.state.organization_id = ctx.org.id
    return ctx


async def _body(request: Request) -> Any:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise ScimError(413, "the body is too large")
    try:
        return json.loads(raw or b"null")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ScimError(400, "the body isn't valid JSON", "invalidSyntax") from exc


def _service(db: AsyncSession, settings: Settings) -> ScimService:
    return ScimService(db, settings)


async def _sync_seats(service: ScimService, ctx: ScimContext) -> None:
    if service.seats_changed:
        from app.services.billing_service import BillingService

        await BillingService(service.db).sync_seats(ctx.org.id)


def _paging(request: Request) -> tuple[int, int]:
    q = request.query_params
    return proto.paging(q.get("startIndex"), q.get("count"))


def _without_members(request: Request) -> bool:
    excluded = request.query_params.get("excludedAttributes", "")
    return "members" in {a.strip().lower() for a in excluded.split(",")}


# -- discovery ------------------------------------------------------------------------------


@router.get("/ServiceProviderConfig")
async def service_provider_config(
    _ctx: ScimContext = Depends(scim_auth), settings: Settings = Depends(get_settings)
) -> JSONResponse:
    return scim_response(proto.service_provider_config(_base(settings)))


def _base(settings: Settings) -> str:
    return settings.public_api_url.rstrip("/") + "/scim/v2"


@router.get("/ResourceTypes")
async def resource_types(
    _ctx: ScimContext = Depends(scim_auth), settings: Settings = Depends(get_settings)
) -> JSONResponse:
    items = proto.resource_types(_base(settings))
    return scim_response(proto.list_response(items, total=len(items), start_index=1))


@router.get("/ResourceTypes/{type_id}")
async def resource_type(
    type_id: str, _ctx: ScimContext = Depends(scim_auth), settings: Settings = Depends(get_settings)
) -> JSONResponse:
    for item in proto.resource_types(_base(settings)):
        if item["id"] == type_id:
            return scim_response(item)
    raise ScimError(404, "resource type not found")


@router.get("/Schemas")
async def schemas(_ctx: ScimContext = Depends(scim_auth)) -> JSONResponse:
    items = proto.schemas()
    return scim_response(proto.list_response(items, total=len(items), start_index=1))


@router.get("/Schemas/{schema_id}")
async def schema(schema_id: str, _ctx: ScimContext = Depends(scim_auth)) -> JSONResponse:
    for item in proto.schemas():
        if item["id"] == schema_id:
            return scim_response(item)
    raise ScimError(404, "schema not found")


# -- users ----------------------------------------------------------------------------------


@router.get("/Users")
async def list_users(
    request: Request,
    ctx: ScimContext = Depends(scim_auth),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    start, count = _paging(request)
    body = await _service(db, settings).list_users(
        ctx, request.query_params.get("filter"), start, count
    )
    return scim_response(body)


@router.post("/Users")
async def create_user(
    request: Request,
    ctx: ScimContext = Depends(scim_auth),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    service = _service(db, settings)
    resource = await service.create_user(ctx, await _body(request))
    await _sync_seats(service, ctx)
    meta: dict[str, str] = resource["meta"]  # type: ignore[assignment]
    return scim_response(resource, status.HTTP_201_CREATED, Location=meta["location"])


@router.get("/Users/{user_id}")
async def get_user(
    user_id: str,
    ctx: ScimContext = Depends(scim_auth),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    return scim_response(await _service(db, settings).get_user(ctx, user_id))


@router.put("/Users/{user_id}")
async def replace_user(
    user_id: str,
    request: Request,
    ctx: ScimContext = Depends(scim_auth),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    service = _service(db, settings)
    resource = await service.replace_user(ctx, user_id, await _body(request))
    await _sync_seats(service, ctx)
    return scim_response(resource)


@router.patch("/Users/{user_id}")
async def patch_user(
    user_id: str,
    request: Request,
    ctx: ScimContext = Depends(scim_auth),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    service = _service(db, settings)
    resource = await service.patch_user(ctx, user_id, await _body(request))
    await _sync_seats(service, ctx)
    return scim_response(resource)


@router.delete("/Users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    ctx: ScimContext = Depends(scim_auth),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    service = _service(db, settings)
    await service.delete_user(ctx, user_id)
    await _sync_seats(service, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -- groups ---------------------------------------------------------------------------------


@router.get("/Groups")
async def list_groups(
    request: Request,
    ctx: ScimContext = Depends(scim_auth),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    start, count = _paging(request)
    body = await _service(db, settings).list_groups(
        ctx,
        request.query_params.get("filter"),
        start,
        count,
        with_members=not _without_members(request),
    )
    return scim_response(body)


@router.post("/Groups")
async def create_group(
    request: Request,
    ctx: ScimContext = Depends(scim_auth),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    resource = await _service(db, settings).create_group(ctx, await _body(request))
    meta: dict[str, str] = resource["meta"]  # type: ignore[assignment]
    return scim_response(resource, status.HTTP_201_CREATED, Location=meta["location"])


@router.get("/Groups/{group_id}")
async def get_group(
    group_id: str,
    request: Request,
    ctx: ScimContext = Depends(scim_auth),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    return scim_response(
        await _service(db, settings).get_group(
            ctx, group_id, with_members=not _without_members(request)
        )
    )


@router.put("/Groups/{group_id}")
async def replace_group(
    group_id: str,
    request: Request,
    ctx: ScimContext = Depends(scim_auth),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    return scim_response(
        await _service(db, settings).replace_group(ctx, group_id, await _body(request))
    )


@router.patch("/Groups/{group_id}")
async def patch_group(
    group_id: str,
    request: Request,
    ctx: ScimContext = Depends(scim_auth),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    return scim_response(
        await _service(db, settings).patch_group(ctx, group_id, await _body(request))
    )


@router.delete("/Groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: str,
    ctx: ScimContext = Depends(scim_auth),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    await _service(db, settings).delete_group(ctx, group_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -- org admins: setup ----------------------------------------------------------------------


def _session_only(ctx: OrgContext) -> None:
    if ctx.principal.via != "session":
        raise forbidden(
            "SCIM settings need a signed-in session, not an API token", "session_required"
        )


async def config_read(service: ScimService, org_id: Any) -> ScimConfigRead:
    base = service.base_url()
    allowed = await service.allowed_by_plan(org_id)
    directory = await service.directory(org_id)
    if directory is None:
        return ScimConfigRead(
            configured=False, allowed_by_plan=allowed, base_url=base, users_url=base + "/Users"
        )
    summary = await service.summary(org_id)
    mapping = directory.group_roles or {}
    return ScimConfigRead(
        configured=True,
        allowed_by_plan=allowed,
        active=directory.active,
        base_url=base,
        users_url=base + "/Users",
        token_hint=directory.token_hint or None,
        token_created_at=directory.token_created_at,
        created_at=directory.created_at,
        last_sync_at=directory.last_sync_at,
        group_roles=mapping,
        active_users=summary["active_users"],  # type: ignore[arg-type]
        deactivated_users=summary["deactivated_users"],  # type: ignore[arg-type]
        groups=[
            ScimGroupSummary(display_name=name, members=n, mapped_role=mapping.get(name.lower()))
            for name, n in summary["groups"]  # type: ignore[attr-defined]
        ],
    )


@org_router.get("/{slug}/scim", response_model=ScimConfigRead)
async def get_scim(
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ScimConfigRead:
    return await config_read(ScimService(db, settings), ctx.org.id)


@org_router.post("/{slug}/scim/token", response_model=ScimTokenRead)
async def issue_scim_token(
    request: Request,
    response: Response,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ScimTokenRead:
    """Create the directory (and switch it on) or rotate its token. The token is shown once;
    a rotated token stops working immediately."""
    _session_only(ctx)
    service = ScimService(db, settings)
    org_id = ctx.org.id
    _directory, raw, created = await service.issue_token(
        ctx.org, ctx.principal.user, request_info(request)
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    read = await config_read(service, org_id)
    return ScimTokenRead(**read.model_dump(), token=raw)


@org_router.patch("/{slug}/scim", response_model=ScimConfigRead)
async def update_scim(
    body: ScimConfigUpdate,
    request: Request,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ScimConfigRead:
    _session_only(ctx)
    service = ScimService(db, settings)
    org_id = ctx.org.id
    await service.update(
        ctx.org,
        actor=ctx.principal.user,
        actor_role=ctx.role,
        active=body.active,
        group_roles=dict(body.group_roles) if body.group_roles is not None else None,
        info=request_info(request),
    )
    return await config_read(service, org_id)


@org_router.delete("/{slug}/scim", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scim(
    request: Request,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> None:
    _session_only(ctx)
    await ScimService(db, settings).delete_directory(
        ctx.org, ctx.principal.user, request_info(request)
    )
