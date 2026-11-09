"""GET /realtime/stream (generated): Server-Sent Events for the records of this app.

Resume with the `Last-Event-ID` header or `?last_event_id=`: events after the cursor are replayed in order,
exactly once, then the stream follows live. Without a cursor only new events are sent. A cursor that cannot
be replayed (pruned, or from another database) gets one `resync` event carrying the new cursor: reload.

Each caller receives only events of entities they may `list`, and for owner / tenant scoped entities only
events of rows inside that scope (the same rule as the entity's list). Frames hold ids, never field values.
The stream ends after 300 s so that the caller is authorised again when it reconnects."""

import asyncio
import time
import typing as _t
from collections.abc import AsyncIterator, Callable

import fastapi as _fa
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from app.auth.deps import CurrentUser
from app.core import errors as _errors
from app.db import SessionDep
from app.db import session_factory as _sessions
from app.models._base import utcnow as _utcnow
from app.realtime import protocol as _rt
from app.realtime import service as _svc
from app.routers.expenses import _ACCESS as _ACCESS_expenses
from app.routers.payrolls import _ACCESS as _ACCESS_payrolls

router = _fa.APIRouter(tags=["realtime"])
BATCH = 200

_limiter = _rt.ConnectionLimiter()
_reconnects = _rt.ReconnectGuard()


def reset_state() -> None:
    """Tests only: forget the stream slots and the reconnect history."""
    global _limiter, _reconnects  # noqa: PLW0603
    _limiter = _rt.ConnectionLimiter()
    _reconnects = _rt.ReconnectGuard()


async def _rules(user: _t.Any) -> dict[str, dict[str, _t.Any]]:
    """entity -> the row scope of the caller's `list` (an entity the caller may not list is absent)."""
    rules: dict[str, dict[str, _t.Any]] = {}
    try:
        rules["Expense"] = dict((await _ACCESS_expenses["list"](user)).scope)
    except _errors.AppError:
        pass
    try:
        rules["Payroll"] = dict((await _ACCESS_payrolls["list"](user)).scope)
    except _errors.AppError:
        pass
    return rules


async def _frames(
    request: _fa.Request,
    rules: dict[str, dict[str, _t.Any]],
    last_id: int | None,
    release: Callable[[], None],
) -> AsyncIterator[bytes]:
    started = time.monotonic()

    async def read(cursor: int) -> list[_t.Any]:
        async with _sessions() as s, s.begin():
            return await _svc.events_after(s, cursor, BATCH)

    try:
        async with _sessions() as s, s.begin():
            floor, head = await _svc.floor_and_head(s)
        if last_id is None:
            cursor = max(floor, head)
        elif _rt.needs_resync(last_id, floor, head):
            cursor = floor if last_id < floor else max(floor, head)
            yield _rt.encode_event(_rt.Event("system", "resync", {"reason": "cursor_unavailable"}, _utcnow(), cursor))
        else:
            cursor = last_id
        yield _rt.encode_comment("open")
        last_sent = time.monotonic()
        idle = _rt.POLL_SECONDS
        while True:
            if await request.is_disconnected():
                return
            if time.monotonic() - started >= _rt.MAX_STREAM_SECONDS:
                return  # the client reconnects with Last-Event-ID and is authorised again
            batch = await read(cursor)  # a short session: nothing is held while the stream sleeps
            idle = _rt.POLL_SECONDS if batch else min(idle * 1.5, _rt.IDLE_POLL_SECONDS)
            for row in batch:
                cursor = row.id  # advance past events this caller may not see, too
                if _svc.visible(row, rules):
                    yield _rt.encode_event(_svc.to_event(row))
                    last_sent = time.monotonic()
            if len(batch) >= BATCH:
                continue  # more waiting: drain before sleeping
            if time.monotonic() - last_sent >= _rt.HEARTBEAT_SECONDS:
                yield _rt.encode_comment()
                last_sent = time.monotonic()
            await asyncio.sleep(idle)
    finally:
        release()


@router.get("/realtime/stream")
async def stream(
    request: _fa.Request,
    session: SessionDep,
    user: CurrentUser,
    last_event_id_q: _t.Annotated[str | None, _fa.Query(alias="last_event_id", max_length=40)] = None,
) -> _fa.Response:
    user_key = str(user.id)
    rules = await _rules(user)
    # The request's own session (sign-in check, access rules) would stay checked out for the whole stream:
    # give its connection back now. The stream below opens a short session per poll.
    await session.close()
    if _limiter.at_capacity():
        raise _errors.AppError(
            _rt.STREAMS_AT_CAPACITY, "the server has all its live streams in use; try again shortly", 503
        )
    if not _limiter.acquire(user_key):
        raise _errors.AppError(
            _rt.TOO_MANY_STREAMS, f"at most {_limiter.max} live streams per person; close one first", 429
        )
    released = False

    def release() -> None:
        nonlocal released
        if not released:
            released = True
            _limiter.release(user_key)

    try:
        retry = _reconnects.check(user_key)
        if retry is not None:
            release()
            return JSONResponse(
                {
                    "code": _rt.RECONNECT_THROTTLED,
                    "message": "reconnecting too often; wait before opening the stream again",
                    "details": [],
                },
                status_code=429,
                headers={"Retry-After": str(retry)},
            )
        last_id = _rt.parse_last_event_id(request.headers.get("last-event-id"))
        if last_id is None:
            last_id = _rt.parse_last_event_id(last_event_id_q)
        body = _frames(request, rules, last_id, release)
    except BaseException:
        release()
        raise
    return StreamingResponse(
        body,
        background=BackgroundTask(release),  # also runs when the generator never started
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
