"""Run organization deletions whose grace period has ended (owner decision, 2026-10-26).

An owner's deletion request blocks the org at once and schedules the deletion
(`organizations.deletion_scheduled_for`, default 7 days, an operator can change it). Until
then the owner can revoke it. This job carries out the due ones:

    python -m app.services.org_deletion_service      # from cron, e.g. hourly

Operators can also delete early from the console
(`POST /admin/organizations/{id}/deletion/execute`).
"""

import asyncio
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import Organization, Subscription
from app.services import audit_service
from app.services.billing_service import has_live_stripe_subscription
from app.services.organization_service import OrganizationService

log = structlog.get_logger()


async def execute(
    session: AsyncSession,
    organization_id: uuid.UUID,
    *,
    actor_id: uuid.UUID | None = None,
    actor_email: str | None = None,
    reason: str = "grace period ended",
) -> int:
    """Delete one org that has a pending request. Returns how many projects went with it."""
    projects = await OrganizationService(session).execute_deletion(organization_id)
    await audit_service.record(
        session,
        action="org.deleted",
        actor_id=actor_id,
        actor_email=actor_email,
        via="session" if actor_id else "system",
        organization_id=organization_id,
        target_type="organization",
        target_id=organization_id,
        detail={"projects_deleted": projects, "reason": reason[:200]},
    )
    await session.commit()
    return projects


async def run_due(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Delete every org whose scheduled time has passed. Returns how many were deleted."""
    cutoff = now or datetime.now(UTC)
    due = list(
        (
            await session.execute(
                select(Organization.id).where(
                    Organization.deleted_at.is_(None),
                    Organization.deletion_requested_at.is_not(None),
                    Organization.deletion_scheduled_for <= cutoff,
                )
            )
        ).scalars()
    )
    done = 0
    for org_id in due:
        try:
            if await _took_a_subscription(session, org_id):
                continue
            await execute(session, org_id)
        except Exception as exc:  # noqa: BLE001 — one bad org must not stop the others
            await session.rollback()
            log.error("org_deletion_failed", organization_id=str(org_id), error=type(exc).__name__)
            continue
        done += 1
    return done


async def _took_a_subscription(session: AsyncSession, organization_id: uuid.UUID) -> bool:
    """The request-time check can go stale: an owner may subscribe during the grace period.
    Such an org is left alone for an operator to look at."""
    sub = await session.get(Subscription, organization_id)
    if sub is None or not has_live_stripe_subscription(sub):
        return False
    log.warning("org_deletion_skipped_subscription", organization_id=str(organization_id))
    return True


async def _main() -> None:
    from app.db import get_session_factory

    async with get_session_factory()() as session:
        print({"deleted": await run_due(session)})  # noqa: T201 — a cron job's output


if __name__ == "__main__":
    asyncio.run(_main())
