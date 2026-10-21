from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session

router = APIRouter(tags=["health"])


@router.get("/health", status_code=status.HTTP_200_OK)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", status_code=status.HTTP_200_OK)
async def ready(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    # Catches both SQLAlchemy's own errors and driver-level connection failures
    # (e.g. asyncpg raises a raw ConnectionRefusedError when Postgres is down,
    # which SQLAlchemy does not wrap since no DBAPI connection was established).
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc
    return {"status": "ready"}
