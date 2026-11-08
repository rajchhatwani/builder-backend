"""Fields numbered by a sequence (generated).

A numbered field is owned by the platform: a create draws the next number of the sequence INSIDE the
transaction that inserts the row, so

* a create that fails or is rolled back burns no number (the counter moves only with the commit),
* parallel creates are serialised on the counter row and get distinct, consecutive numbers,
* a caller can neither choose the number on create nor change it later.

The draw is `sequences.next_number`: there is no second counter. The counter row stays locked until the
create commits or rolls back, so numbered creates of one sequence run one after another.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.runtime_config import sequences


async def draw(
    session: AsyncSession,
    sequence: str,
    *,
    tenant_id: uuid.UUID | None,
    per_tenant: bool,
    as_int: bool,
) -> Any:
    """The next number as the field stores it: text, or an int for a bare counter."""
    if per_tenant and tenant_id is None:
        raise AppError("forbidden", "you do not belong to a tenant", 403)  # no tenant, no counter
    number = await sequences.next_number(session, sequence, tenant_id=tenant_id if per_tenant else None)
    return int(number) if as_int else number


def refuse_change(fields: tuple[str, ...], data: dict[str, Any]) -> None:
    """422 when a write tries to set a numbered field."""
    for name in fields:
        if name in data:
            raise AppError("field_is_managed", f"{name} is assigned by the system and cannot be changed", 422)
