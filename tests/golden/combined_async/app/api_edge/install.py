"""Wires the API edge into the app (generated): the middleware, the application-wide guard, the shared
transaction of idempotent requests and the /api-versions changelog."""

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_edge import config, deferral, versioning
from app.api_edge.guard import guard
from app.api_edge.middleware import ApiEdgeMiddleware
from app.db import get_session, session_factory

router = APIRouter(tags=["api-versions"])


@router.get("/api-versions")
async def api_versions() -> dict[str, object]:
    """The versions this API has had, newest first, and the one a client gets without a header."""
    return versioning.changelog()


async def edge_session(request: Request) -> AsyncIterator[AsyncSession]:
    """The request's session. An idempotent request uses the one its middleware opened (it also
    commits it); every other request gets a session of its own, as without the edge."""
    edge = getattr(request.state, "edge", None)
    if edge is not None and edge.session is not None:
        yield edge.session
        return
    async with session_factory() as session:
        yield session


def install(app: FastAPI) -> None:
    config.trusted_proxies()  # a bad API_EDGE_TRUSTED_PROXIES stops the app here
    versioning.check_registry()  # a transformer for an undeclared version stops the app here
    deferral.install()  # an app without the expected lifecycle stops here
    app.add_middleware(ApiEdgeMiddleware)
    app.router.dependencies.append(Depends(guard))  # before any router is included: it covers them all
    app.dependency_overrides[get_session] = edge_session
    app.include_router(router)
