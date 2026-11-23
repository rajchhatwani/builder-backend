"""Public API (generated): /public/v1/...

Read-only, authenticated by an API key in the `X-API-Key` header and by nothing else: a key in the query string is
refused (and never logged), a user token is not accepted here, and a key never opens an admin route. Default deny: the
key must be active, hold the entity as a scope, and a sandbox key only reaches sandbox entities. Only the fields the
spec lists (plus id) are returned, and only the key's own tenant's rows. Every response carries the rate-limit headers;
over the limit a call gets 429 with Retry-After."""

import dataclasses
import datetime as _dt
import importlib
import uuid as _uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.security import APIKeyHeader

from app.core.errors import AppError
from app.db import SessionDep
from app.platform_api import service, settings

_HEADER = "X-API-Key"
_QUERY_NAMES = {"api_key", "apikey", "api-key", "key", "x-api-key", "access_token", "token"}
_key_header = APIKeyHeader(name=_HEADER, auto_error=False, description="API key from /platform/keys")


class PublicDenied(AppError):
    """An AppError that also carries response headers (rate limit headers, Retry-After)."""

    def __init__(self, code: str, message: str, status_code: int, headers: dict[str, str] | None = None) -> None:
        super().__init__(code, message, status_code)
        self.headers = headers or {}


class _PublicRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except PublicDenied as exc:
                body = {"code": exc.code, "message": exc.message, "details": []}
                return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)

        return handler


router = APIRouter(prefix="/public/v1", tags=["public-api"], route_class=_PublicRoute)


@dataclasses.dataclass(frozen=True)
class Caller:
    key_id: _uuid.UUID
    tenant_id: _uuid.UUID | None
    environment: str
    scopes: tuple[str, ...]
    limit: int
    remaining: int
    expires_at: _dt.datetime


def _unauthorized(message: str = "a valid API key is required in the X-API-Key header") -> PublicDenied:
    return PublicDenied("unauthorized", message, 401)


def _rate_headers(limit: int, remaining: int) -> dict[str, str]:
    return {"X-RateLimit-Limit": str(limit), "X-RateLimit-Remaining": str(max(remaining, 0))}


def _gate(entity: str | None) -> Callable[..., Awaitable[Caller]]:
    async def dependency(request: Request, response: Response, api_key: Annotated[str | None, Depends(_key_header)]) -> Caller:
        for name, value in request.query_params.multi_items():
            if name.lower() in _QUERY_NAMES or value.startswith(service.KEY_PREFIX + "_"):
                raise _unauthorized("API keys are accepted only in the X-API-Key header")
        if not api_key:
            raise _unauthorized()
        row = await service.authenticate_key(api_key)
        if row is None:
            raise _unauthorized()
        status = service.key_status(row)
        if status != "active":
            await service.audit_denial(row, status)
            raise _unauthorized(f"this API key is {status}")
        count, limit, retry_after = await service.hit_limit(row)
        headers = _rate_headers(limit, limit - count)
        if count > limit:
            if count == limit + 1:  # the first refusal of a window is audited, not every one
                await service.audit_denial(row, "rate_limited", limit=limit)
            raise PublicDenied("rate_limited", "too many requests", 429, {**headers, "Retry-After": str(retry_after)})
        if entity is not None:
            cfg = settings.ENTITIES[entity]
            if entity not in row.scopes:
                await service.audit_denial(row, "scope", entity=entity)
                raise PublicDenied("forbidden", "this API key may not read that resource", 403, headers)
            if row.environment == "sandbox" and not cfg["sandbox"]:
                await service.audit_denial(row, "sandbox", entity=entity)
                raise PublicDenied("forbidden", "this API key may not read that resource", 403, headers)
        response.headers.update(headers)
        return Caller(row.id, row.tenant_id, row.environment, tuple(row.scopes), limit, limit - count, row.expires_at)

    return dependency


@router.get("/me")
async def me(caller: Annotated[Caller, Depends(_gate(None))]) -> dict[str, Any]:
    return jsonable_encoder(
        {
            "key_id": caller.key_id,
            "environment": caller.environment,
            "scopes": list(caller.scopes),
            "rate_limit": caller.limit,
            "remaining": max(caller.remaining, 0),
            "expires_at": caller.expires_at,
        }
    )


def _model(entity: str) -> Any:
    cfg = settings.ENTITIES[entity]
    return getattr(importlib.import_module(cfg["module"]), cfg["class"])


def _visible(model: Any, caller: Caller) -> list[Any]:
    """Conditions every public read carries: the key's tenant, no soft-deleted rows."""
    conditions: list[Any] = []
    if hasattr(model, "tenant_id"):
        conditions.append(model.tenant_id == caller.tenant_id)
    if hasattr(model, "deleted_at"):
        conditions.append(model.deleted_at.is_(None))
    return conditions


def _shape(entity: str, row: Any) -> dict[str, Any]:
    data = {"id": row.id, **{name: getattr(row, name) for name in settings.ENTITIES[entity]["fields"]}}
    return jsonable_encoder(data)  # type: ignore[no-any-return]


def _register(entity: str, cfg: dict[str, Any]) -> None:
    path = "/" + cfg["plural_path"]
    gate = Depends(_gate(entity))

    async def list_rows(
        session: SessionDep,
        caller: Annotated[Caller, gate],
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    ) -> list[dict[str, Any]]:
        model = _model(entity)
        stmt = sa.select(model).where(*_visible(model, caller))
        order = [model.created_at] if hasattr(model, "created_at") else []
        rows = (await session.execute(stmt.order_by(*order, model.id).limit(limit).offset(offset))).scalars()
        return [_shape(entity, row) for row in rows]

    async def get_row(
        item_id: _uuid.UUID, session: SessionDep, caller: Annotated[Caller, gate]
    ) -> dict[str, Any]:
        model = _model(entity)
        stmt = sa.select(model).where(model.id == item_id, *_visible(model, caller))
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:  # unknown id and another tenant's id answer the same
            raise PublicDenied("not_found", "resource not found", 404, _rate_headers(caller.limit, caller.remaining))
        return _shape(entity, row)

    router.add_api_route(path, list_rows, methods=["GET"], name=f"public_list_{cfg['plural_path']}")
    router.add_api_route(path + "/{item_id}", get_row, methods=["GET"], name=f"public_get_{cfg['plural_path']}")


for _entity, _cfg in settings.ENTITIES.items():
    _register(_entity, _cfg)
