"""Application entry point (generated)."""

import importlib
import pkgutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import custom_routers
from app.auth.config import get_auth_settings
from app.auth.provider_lock import ensure_provider_lock
from app.auth.router import router as _auth_router
from app.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import RequestIdMiddleware, configure_logging
from app.db import engine
from app.routers._health import router as _health_router
from app.routers.leave_requests import router as leave_requests_router
from app.state_machines.router import router as _state_machines_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    get_auth_settings()  # a missing secret stops the app here, with a clear message
    await ensure_provider_lock()  # refuses to start on a database used by another provider
    yield
    await engine.dispose()


def include_custom_routers(app: FastAPI) -> None:
    """Mount every module in app/custom_routers that defines a `router`."""
    for module_info in sorted(pkgutil.iter_modules(custom_routers.__path__), key=lambda m: m.name):
        module = importlib.import_module(f"{custom_routers.__name__}.{module_info.name}")
        router = getattr(module, "router", None)
        if router is not None:
            app.include_router(router)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title='Leave Flow', version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(_health_router)
    app.include_router(_auth_router)
    app.include_router(leave_requests_router)
    app.include_router(_state_machines_router)
    include_custom_routers(app)
    return app


app = create_app()
