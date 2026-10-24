import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AuditResult
from app.models.platform import AuditLog

# Keys that must never appear in the free-form `detail`, whatever the caller passes.
_FORBIDDEN_DETAIL_KEYS = ("password", "token", "secret", "authorization", "cookie", "otp")


def _clean_detail(detail: dict[str, object] | None) -> dict[str, object] | None:
    if not detail:
        return None
    cleaned: dict[str, object] = {}
    for key, value in detail.items():
        if any(bad in key.lower() for bad in _FORBIDDEN_DETAIL_KEYS):
            continue
        cleaned[key] = value if isinstance(value, int | float | bool | None) else str(value)[:200]
    return cleaned or None


async def record(
    session: AsyncSession,
    *,
    action: str,
    result: AuditResult = AuditResult.ok,
    actor_id: uuid.UUID | None = None,
    actor_email: str | None = None,
    via: str = "session",
    target_type: str | None = None,
    target_id: str | uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    client_ip: str | None = None,
    request_id: str | None = None,
    detail: dict[str, object] | None = None,
) -> None:
    """Add an audit row to the open transaction. The caller commits (and must commit before it
    raises on a failure path, or the row rolls back with everything else)."""
    session.add(
        AuditLog(
            actor_id=actor_id,
            actor_email=actor_email,
            via=via,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            project_id=project_id,
            result=result,
            client_ip=client_ip,
            request_id=request_id,
            detail=_clean_detail(detail),
        )
    )


async def search(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    actor_id: uuid.UUID | None = None,
    action: str | None = None,
    project_id: uuid.UUID | None = None,
    since: datetime | None = None,
    result: AuditResult | None = None,
) -> tuple[list[AuditLog], int]:
    conditions = []
    if actor_id is not None:
        conditions.append(AuditLog.actor_id == actor_id)
    if action:
        conditions.append(AuditLog.action.startswith(action))
    if project_id is not None:
        conditions.append(AuditLog.project_id == project_id)
    if since is not None:
        conditions.append(AuditLog.at >= since)
    if result is not None:
        conditions.append(AuditLog.result == result)
    total = (
        await session.execute(select(func.count()).select_from(AuditLog).where(*conditions))
    ).scalar_one()
    rows = (
        await session.execute(
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars()
    return list(rows), total
