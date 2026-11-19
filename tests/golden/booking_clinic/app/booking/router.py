"""Booking routes (generated, pack booking). Every route needs sign-in; roles come from the spec
(packs.booking: read_roles, book_roles, manage_roles). Rules: app/booking/service.py."""

import datetime as _dt
import typing as _t
import uuid as _uuid

import fastapi as _fa
from fastapi import Depends, Query, Response

from app.auth.deps import CurrentUser
from app.auth.models import AuthUser
from app.booking import config as _config
from app.booking import schemas as _s
from app.booking import service as _svc
from app.core.errors import AppError
from app.core.pagination import Page
from app.db import SessionDep

router = _fa.APIRouter(prefix="/booking", tags=["booking"])


def _allow(user: AuthUser, *groups: tuple[str, ...]) -> AuthUser:
    """Allowed when any group is empty (= any signed-in user) or the caller has a role of any group."""
    if all(groups) and not any(_svc.has_role(user, g) for g in groups):
        raise AppError("forbidden", "you do not have permission to do that", 403)
    return user


async def _reader(user: CurrentUser) -> AuthUser:
    return _allow(user, _config.READ_ROLES, _config.BOOK_ROLES, _config.MANAGE_ROLES)


async def _booker(user: CurrentUser) -> AuthUser:
    return _allow(user, _config.BOOK_ROLES, _config.MANAGE_ROLES)


async def _manager(user: CurrentUser) -> AuthUser:
    return _allow(user, _config.MANAGE_ROLES)


Reader = _t.Annotated[AuthUser, Depends(_reader)]
Booker = _t.Annotated[AuthUser, Depends(_booker)]
Manager = _t.Annotated[AuthUser, Depends(_manager)]
Limit = _t.Annotated[int, Query(ge=1, le=200)]
Offset = _t.Annotated[int, Query(ge=0)]
REPLAYED = {"Idempotent-Replayed": "true"}


@router.post("/resources", response_model=_s.ResourceOut, status_code=201)
async def create_resource(body: _s.ResourceCreate, session: SessionDep, user: Manager) -> _s.ResourceOut:
    return await _svc.create_resource(session, user, body)


@router.get("/resources", response_model=Page[_s.ResourceOut])
async def list_resources(
    session: SessionDep,
    user: Reader,
    limit: Limit = 50,
    offset: Offset = 0,
    kind: _t.Annotated[str | None, Query(max_length=40)] = None,
    active: bool | None = None,
) -> Page[_s.ResourceOut]:
    items, total = await _svc.list_resources(session, user, limit, offset, kind, active)
    return Page[_s.ResourceOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/resources/{resource_id}", response_model=_s.ResourceOut)
async def get_resource(resource_id: _uuid.UUID, session: SessionDep, user: Reader) -> _s.ResourceOut:
    return await _svc.get_resource(session, user, resource_id)


@router.patch("/resources/{resource_id}", response_model=_s.ResourceOut)
async def update_resource(
    resource_id: _uuid.UUID, body: _s.ResourceUpdate, session: SessionDep, user: Manager
) -> _s.ResourceOut:
    return await _svc.update_resource(session, user, resource_id, body)


@router.get("/resources/{resource_id}/availability", response_model=_s.AvailabilityOut)
async def availability(
    resource_id: _uuid.UUID,
    session: SessionDep,
    user: Reader,
    from_: _t.Annotated[_dt.date, Query(alias="from")],
    to: _dt.date,
    include_taken: bool = False,
) -> _s.AvailabilityOut:
    return await _svc.availability(session, user, resource_id, from_, to, include_taken)


@router.get("/resources/{resource_id}/capacity", response_model=_s.CapacityOut)
async def capacity(
    resource_id: _uuid.UUID, session: SessionDep, user: Reader, starts_at: _dt.datetime, ends_at: _dt.datetime
) -> _s.CapacityOut:
    return await _svc.capacity(session, user, resource_id, starts_at, ends_at)


@router.post(
    "/bookings",
    response_model=_s.BookingOut,
    status_code=201,
    description=(
        "Hold or book a slot. With an idempotency_key a replay returns the same booking (200, Idempotent-Replayed) "
        "while it is held or confirmed; once it is expired or cancelled the replay is 409 idempotency_key_spent: use a new key."
    ),
)
async def create_booking(body: _s.BookingCreate, response: Response, session: SessionDep, user: Booker) -> _s.BookingOut:
    booking, replayed = await _svc.create_booking(session, user, body)
    if replayed:
        response.status_code = 200
        response.headers.update(REPLAYED)
    return booking


@router.get("/bookings", response_model=Page[_s.BookingOut])
async def list_bookings(
    session: SessionDep,
    user: Reader,
    limit: Limit = 50,
    offset: Offset = 0,
    resource_id: _uuid.UUID | None = None,
    status: _t.Annotated[_t.Literal["held", "confirmed", "cancelled", "expired"] | None, Query()] = None,
    from_: _t.Annotated[_dt.datetime | None, Query(alias="from")] = None,
    to: _dt.datetime | None = None,
) -> Page[_s.BookingOut]:
    items, total = await _svc.list_bookings(session, user, limit, offset, resource_id, status, from_, to)
    return Page[_s.BookingOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/bookings/{booking_id}", response_model=_s.BookingOut)
async def get_booking(booking_id: _uuid.UUID, session: SessionDep, user: Reader) -> _s.BookingOut:
    return await _svc.get_booking(session, user, booking_id)


@router.post(
    "/bookings/{booking_id}/confirm",
    response_model=_s.BookingOut,
    description="Confirm a hold. Confirming an already confirmed booking returns it unchanged (200); expired or cancelled bookings are refused.",
)
async def confirm_booking(booking_id: _uuid.UUID, session: SessionDep, user: Booker) -> _s.BookingOut:
    return await _svc.confirm_booking(session, user, booking_id)


@router.post(
    "/bookings/{booking_id}/cancel",
    response_model=_s.BookingOut,
    description=(
        "Cancel a booking. The cancellation fee is 0 when the actor is a manager and not the booking's customer "
        "(a manager cancelling someone else's booking never charges them)."
    ),
)
async def cancel_booking(
    booking_id: _uuid.UUID, session: SessionDep, user: Booker, body: _s.CancelIn | None = None
) -> _s.BookingOut:
    return await _svc.cancel_booking(session, user, booking_id, body or _s.CancelIn())


@router.post("/expire", response_model=_s.ExpireOut)
async def expire(session: SessionDep, user: Manager) -> _s.ExpireOut:
    return await _svc.expire_holds(session, user)
