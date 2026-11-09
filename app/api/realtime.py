"""Realtime gateway for builder projects (B4-2, C18).

GET  /projects/{project_id}/events/stream        SSE; resume with Last-Event-ID or ?last_event_id= (viewer)
POST /projects/{project_id}/presence/heartbeat   {where} marks the caller present, ttl 30 s (viewer)
GET  /projects/{project_id}/presence             who is here now (viewer)

Platform side only: generated apps get realtime in a later generator work package. The presence
roster is process-local (one worker's view); events come from the database, so any worker serves
them. The stream never holds a database connection between polls.
"""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.security import current_principal
from app.core import realtime as rt
from app.core import rls
from app.db import get_session, get_session_factory
from app.exceptions import AppError
from app.models.mixins import _utcnow
from app.schemas.realtime import HeartbeatBody, PresenceRead
from app.services import realtime_service as svc
from app.services.access_service import Principal

router = APIRouter(prefix="/projects/{project_id}", tags=["realtime"])

POLL_SECONDS = 0.5
MAX_STREAM_SECONDS = 300.0  # bounds how long a removed member can keep listening
BATCH = 200

_limiter = rt.ConnectionLimiter()
_reconnects = rt.ReconnectGuard()
_books: dict[uuid.UUID, rt.PresenceBook] = {}


def reset_state() -> None:
    """Tests only: forget slots, reconnect history and presence."""
    global _limiter, _reconnects  # noqa: PLW0603
    _limiter = rt.ConnectionLimiter()
    _reconnects = rt.ReconnectGuard()
    _books.clear()


def stream_sessions() -> async_sessionmaker[AsyncSession]:
    """The factory for the stream's short per-poll sessions (tests override this dependency)."""
    return get_session_factory()


def _book(project_id: uuid.UUID) -> rt.PresenceBook:
    return _books.setdefault(project_id, rt.PresenceBook())


def _roster(project_id: uuid.UUID) -> list[rt.PresenceEntry]:
    book = _books.get(project_id)
    if book is None:
        return []
    entries = book.snapshot(time.monotonic())
    if not len(book):
        _books.pop(project_id, None)
    return entries


def _presence_read(entries: list[rt.PresenceEntry]) -> list[PresenceRead]:
    now, mono = _utcnow(), time.monotonic()
    return [
        PresenceRead(
            user_id=e.user_id,
            display=e.display,
            where=e.where,
            last_seen=now - timedelta(seconds=max(0.0, mono - e.last_seen)),
        )
        for e in entries
    ]


@router.post("/presence/heartbeat", status_code=204)
async def heartbeat(
    project_id: uuid.UUID,
    body: HeartbeatBody,
    principal: Principal = Depends(current_principal),
) -> None:
    user = principal.user
    _book(project_id).touch(
        str(user.id), time.monotonic(), body.where.strip(), (user.name or user.email)[:80]
    )


@router.get("/presence", response_model=list[PresenceRead])
async def presence(project_id: uuid.UUID) -> list[PresenceRead]:
    return _presence_read(_roster(project_id))


async def _frames(
    request: Request,
    factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    org_id: uuid.UUID | None,
    last_id: int | None,
    release: Callable[[], None],
) -> AsyncIterator[bytes]:
    started = time.monotonic()

    async def read(cursor: int) -> list[rt.Event]:
        async with factory() as s, s.begin():
            if org_id is not None:
                await rls.bind(s, org_id)
            return await svc.events_after(s, project_id, cursor, BATCH)

    try:
        async with factory() as s, s.begin():
            if org_id is not None:
                await rls.bind(s, org_id)
            floor, head = await svc.floor_and_head(s, project_id)
        if last_id is None:
            cursor = max(floor, head)
        elif rt.needs_resync(last_id, floor, head):
            cursor = floor if last_id < floor else max(floor, head)
            yield rt.encode_event(
                rt.Event(
                    str(project_id), "system", "resync", {"reason": "cursor_unavailable"}, _utcnow(), cursor
                )
            )
        else:
            cursor = last_id
        yield rt.encode_comment("open")
        signature = [(e.user_id, e.where) for e in _roster(project_id)]
        last_sent = time.monotonic()
        while True:
            if await request.is_disconnected():
                return
            if time.monotonic() - started >= MAX_STREAM_SECONDS:
                return  # the client reconnects with Last-Event-ID and is authorised again
            batch = await read(cursor)
            for ev in batch:
                cursor = ev.id or cursor
                yield rt.encode_event(ev)
            if batch:
                last_sent = time.monotonic()
                if len(batch) >= BATCH:
                    continue  # more waiting: drain before sleeping
            entries = _roster(project_id)
            now_sig = [(e.user_id, e.where) for e in entries]
            if now_sig != signature:
                signature = now_sig
                users = [{"user_id": e.user_id, "display": e.display, "where": e.where} for e in entries]
                yield rt.encode_event(
                    rt.Event(str(project_id), "presence", "presence", {"users": users}, _utcnow())
                )
                last_sent = time.monotonic()
            if time.monotonic() - last_sent >= rt.HEARTBEAT_SECONDS:
                yield rt.encode_comment()
                last_sent = time.monotonic()
            await asyncio.sleep(POLL_SECONDS)
    finally:
        release()


@router.get("/events/stream")
async def stream(
    project_id: uuid.UUID,
    request: Request,
    last_event_id_q: str | None = Query(default=None, alias="last_event_id", max_length=40),
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
    factory: async_sessionmaker[AsyncSession] = Depends(stream_sessions),
) -> StreamingResponse:
    user_key = str(principal.user.id)
    if not _limiter.acquire(user_key):
        raise AppError(
            rt.TOO_MANY_STREAMS,
            f"at most {_limiter.max} live streams per person; close one first",
            429,
        )
    try:
        retry = _reconnects.check((user_key, str(project_id)))
        if retry is not None:
            raise AppError(
                rt.RECONNECT_THROTTLED,
                "reconnecting too often; wait before opening the stream again",
                429,
                headers={"Retry-After": str(retry)},
            )
        last_id = rt.parse_last_event_id(request.headers.get("last-event-id"))
        if last_id is None:
            last_id = rt.parse_last_event_id(last_event_id_q)
        # Hand the request's connection back: the stream opens its own short sessions per poll.
        await db.rollback()
        org_id = getattr(request.state, "organization_id", None)
        released = False

        def release() -> None:
            nonlocal released
            if not released:
                released = True
                _limiter.release(user_key)

        body = _frames(request, factory, project_id, org_id, last_id, release)
    except BaseException:
        _limiter.release(user_key)
        raise
    return StreamingResponse(
        body,
        background=BackgroundTask(release),  # also runs when the generator never started
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
