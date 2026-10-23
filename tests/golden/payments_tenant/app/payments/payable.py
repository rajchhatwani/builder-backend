"""The entity a payment is for (generated): Order.

A payer can start a payment only for a row they are allowed to `get` under that entity's own
permissions (roles, owner, tenant and custom-filter rules all apply), and the amount and currency
are read from the row here on the server, never from the request. Payment results are written back
to the row's status field with an atomic, guarded UPDATE.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.access import build_access
from app.auth.models import AuthUser
from app.core.errors import NotFoundError
from app.models.orders import Order as Model

AMOUNT_FIELD = 'total'
FIXED_CURRENCY: str | None = None
CURRENCY_FIELD: str | None = 'currency'
STATUS_FIELD = 'state'
PENDING = 'open'
PAID = 'settled'
PARTIALLY_REFUNDED = 'part_refunded'
REFUNDED = 'refunded'
SOFT_DELETE = False


@dataclass(frozen=True)
class Payable:
    id: uuid.UUID
    amount: Decimal
    currency: str | None
    status: str


def _visible(user: AuthUser) -> list[Any]:
    """Conditions that restrict the payable to rows this user may read (the entity's `get` rule)."""
    access = build_access(user, roles=('admin', 'manager', 'member'), tenant=True)
    conditions: list[Any] = [Model.__table__.c[name] == value for name, value in access.scope.items()]
    if SOFT_DELETE:
        conditions.append(Model.__table__.c["deleted_at"].is_(None))
    return conditions


async def load_for_payer(session: AsyncSession, user: AuthUser, payable_id: uuid.UUID) -> Payable:
    """The row to pay for, or 404 (also when the user may not see it: no information leaks)."""
    table = Model.__table__
    row = (
        await session.execute(
            sa.select(
                table.c["id"], table.c[AMOUNT_FIELD], table.c[STATUS_FIELD],
                *([table.c[CURRENCY_FIELD]] if CURRENCY_FIELD else []),
            ).where(table.c["id"] == payable_id, *_visible(user))
        )
    ).first()
    if row is None:
        raise NotFoundError("the item to pay for was not found")
    currency = FIXED_CURRENCY if FIXED_CURRENCY else str(row[3])
    return Payable(id=row[0], amount=Decimal(str(row[1])), currency=currency, status=row[2])


async def move_status(
    session: AsyncSession, payable_id: uuid.UUID, sources: tuple[str, ...], target: str
) -> bool:
    """Set the status field to `target` if it is currently one of `sources`. True if it moved."""
    table = Model.__table__
    result = await session.execute(
        sa.update(table)
        .where(table.c["id"] == payable_id, table.c[STATUS_FIELD].in_(sources))
        .values({STATUS_FIELD: target, "updated_at": sa.func.now()})
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]
