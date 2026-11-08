"""Attribute- and policy-based access control, wired into the routes (generated).

`app/auth/policy.py` is the engine and `app/auth/policy_data.py` holds the policies written in the
builder. A route asks `policy_dependency(entity, op)` for an `Access`; it refuses the request
(403) when no policy could ever allow it, and otherwise hands the repository a handle that

  * adds the row condition to every list / get / update / delete query (in SQL, so counts and
    pagination never leak rows the person may not see),
  * checks the values of a new row against the `create` policies,
  * checks that an updated row is still one the person could read afterwards (so a row cannot be
    handed to someone else or moved out of reach in the same request).

Default deny: anything no allow policy covers is refused. A deny policy always wins.
"""

import dataclasses
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
import structlog
from fastapi import Request

from app.auth.access import Access, build_access
from app.auth.deps import CurrentUser
from app.auth.models import AuthUser
from app.auth.policy import Context, load_policy_set, plan
from app.auth.policy_data import POLICY_DATA
from app.auth.service import effective_roles
from app.core.errors import AppError

logger = structlog.get_logger()

# Parsed and checked once, at import: malformed policy data stops the application from starting.
POLICY_SET = load_policy_set(POLICY_DATA)


def _forbidden() -> AppError:
    return AppError("forbidden", "you do not have permission to do that", 403)


def subject_of(user: AuthUser) -> dict[str, Any]:
    """The attributes of the signed-in person that policies may look at (an allow-list)."""
    subject: dict[str, Any] = {
        "id": user.id,
        "email": getattr(user, "email", None),
        "roles": tuple(sorted(effective_roles(user.roles))),
    }
    for name in POLICY_SET.subject_attributes:
        if name not in subject:
            subject[name] = getattr(user, name, None)
    return subject


def env_of(request: Request) -> dict[str, Any]:
    """Facts about the request. Behind a proxy run uvicorn with --proxy-headers and
    --forwarded-allow-ips so that client_ip is the caller's address, not the proxy's."""
    now = datetime.now(UTC)
    return {
        "hour_utc": now.hour,
        "weekday_utc": now.weekday(),
        "client_ip": request.client.host if request.client else None,
    }


class PolicyBinding:
    """What one request may do with one entity operation (handed to the repository)."""

    def __init__(self, entity: str, op: str, context: Context) -> None:
        self.entity = entity
        self.op = op
        self.context = context

    def row_conditions(self, column: Callable[[str], Any]) -> list[Any]:
        decision = plan(POLICY_SET, self.context, self.entity, self.op, column)
        if not decision.allowed:  # cannot happen after the dependency passed; refuse regardless
            return [sa.false()]
        return [] if decision.row_filter is None else [decision.row_filter]

    def check_new_row(self, values: Mapping[str, Any]) -> None:
        """The new row, with the values the caller sent, must satisfy the create policies."""
        decision = plan(POLICY_SET, self.context, self.entity, self.op, sa.column)
        if not decision.allowed or not decision.check_row(values):
            self._deny("the new row is not one you may create")

    def check_changed_row(self, merged: Mapping[str, Any]) -> None:
        """After an update the row must still be readable by the caller, unless they could not
        read this entity at all (a write-only role)."""
        readable = plan(POLICY_SET, self.context, self.entity, "get", sa.column)
        if readable.allowed and not readable.check_row(merged):
            self._deny("the change would move the row out of your reach")

    def _deny(self, reason: str) -> None:
        logger.info(
            "authz_denied",
            entity=self.entity,
            op=self.op,
            user_id=str(self.context.subject.get("id")),
            reason=reason,
        )
        raise _forbidden()


def policy_dependency(
    entity: str, op: str, *, stamp: bool = False, tenant: bool = False
) -> Callable[..., Awaitable[Access]]:
    async def dependency(request: Request, user: CurrentUser) -> Access:
        context = Context(subject=subject_of(user), env=env_of(request))
        decision = plan(POLICY_SET, context, entity, op, sa.column)
        if not decision.allowed:
            logger.info(
                "authz_denied",
                entity=entity,
                op=op,
                user_id=str(user.id),
                reason=decision.reason,
                policies=list(decision.deny_ids),
            )
            raise _forbidden()
        base = build_access(user, stamp=stamp, tenant=tenant)
        return dataclasses.replace(base, policy=PolicyBinding(entity, op, context))

    return dependency
