import logging

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import entities, fields, generate, health, projects, relations, spec
from app.config import get_settings
from app.errors import register_exception_handlers


def configure_logging(log_level: str) -> None:
    logging.basicConfig(level=log_level, format="%(message)s")
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(log_level)),
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
    )


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="Backend Builder", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition", "X-Generation-Id", "X-Spec-Hash"],
    )
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(projects.router)
    app.include_router(entities.router)
    app.include_router(fields.router)
    app.include_router(relations.router)
    app.include_router(spec.router)
    app.include_router(generate.router)
    return app


app = create_app()
