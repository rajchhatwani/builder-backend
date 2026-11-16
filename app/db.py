from collections.abc import AsyncGenerator
import asyncio
import weakref
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_factory()() as session:
        yield session


_SIDE_ENGINES: dict[str, AsyncEngine] = {}
_SIDE_SLOTS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = weakref.WeakKeyDictionary()
SIDE_CONNECTIONS = 4


def side_engine(bind: object) -> AsyncEngine:
    """Engine for side connections (refusal events, advisory locks) that never draws on the caller's
    pool: a request already holds one pooled connection, so a second one from the same pool can
    deadlock a burst of requests (F-0276). NullPool + `side_slot()` bound the extra connections."""
    sync = bind.sync_engine if isinstance(bind, AsyncEngine) else bind  # type: ignore[attr-defined]
    url = sync.url
    key = url.render_as_string(hide_password=False)
    eng = _SIDE_ENGINES.get(key)
    if eng is None:
        eng = _SIDE_ENGINES[key] = create_async_engine(url, poolclass=NullPool)
    return eng


def side_slot() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    sem = _SIDE_SLOTS.get(loop)
    if sem is None:
        sem = _SIDE_SLOTS[loop] = asyncio.Semaphore(SIDE_CONNECTIONS)
    return sem
