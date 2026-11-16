"""Shared guard for builder routes that edit access rules row by row."""

import uuid
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_layers import weakens
from app.exceptions import AppError

_T = TypeVar("_T")


async def guarded_write(
    session: AsyncSession, project_id: uuid.UUID, confirm: bool, write: Callable[[], Awaitable[_T]]
) -> _T:
    """Run `write` (flush only), refuse with 409 access_weakened if it gives a role more access
    unless `confirm`, else commit. Same guard as PUT /authorization and spec ops."""
    if confirm:
        result = await write()
        await session.commit()
        return result
    from app.services.spec_service import SpecService  # late: spec_service imports models

    before = await SpecService(session).assemble(project_id)
    result = await write()
    await session.flush()
    session.expire_all()
    after = await SpecService(session).assemble(project_id)
    gained = weakens(before, after)
    if gained:
        await session.rollback()
        raise AppError(
            code="access_weakened",
            message=f"this change gives {len({c['role'] for c in gained})} role(s) more "
            "access; review POST /access/diff and repeat with confirm_weakening",
            status_code=409,
            details=gained[:100],
        )
    await session.commit()
    return result
