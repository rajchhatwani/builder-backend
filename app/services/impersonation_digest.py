"""The daily support-access digest (§4.5): every "view as" session of the last day, for a security
channel. Built from `impersonation_sessions` and the audit log; delivered to a Slack-compatible
webhook and/or an e-mail address. A day with no sessions still sends a message, so silence means
the job is broken. Delivery is recorded (`impersonation.digest_sent`, never the webhook URL), which
also keeps a re-run from sending twice.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.config import Settings
from app.models.platform import AuditLog, ImpersonationSession, Organization, PlatformUser
from app.services import audit_service, mail_service

log = structlog.get_logger()
TIMEOUT_SECONDS = 10.0


@dataclass
class Digest:
    since: datetime
    until: datetime
    sessions: list[dict[str, object]]
    refused: int
    text: str


@dataclass
class RunResult:
    sent: bool
    channels: list[str] = field(default_factory=list)
    skipped: str | None = None
    error: str | None = None
    digest: Digest | None = None


def _hm(value: datetime | None) -> str:
    return value.astimezone(UTC).strftime("%H:%M") if value else "-"


async def build(db: AsyncSession, since: datetime, until: datetime) -> Digest:
    op, target = aliased(PlatformUser), aliased(PlatformUser)
    rows = (
        await db.execute(
            select(ImpersonationSession, op.email, target.email, Organization.slug)
            .join(op, op.id == ImpersonationSession.operator_id)
            .join(target, target.id == ImpersonationSession.target_user_id)
            .join(Organization, Organization.id == ImpersonationSession.organization_id)
            .where(
                ImpersonationSession.created_at >= since, ImpersonationSession.created_at < until
            )
            .order_by(ImpersonationSession.created_at)
        )
    ).all()
    audit = (
        (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.at >= since,
                    AuditLog.action.in_(
                        ["impersonation.writes_enabled", "impersonation.denied", "project.change"]
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    writes_sessions = {
        (a.detail or {}).get("session_id")
        for a in audit
        if a.action == "impersonation.writes_enabled"
    }
    refused = sum(
        1
        for a in audit
        if a.action == "impersonation.denied"
        and (a.detail or {}).get("why") == "org_policy"
        and a.at < until
    )
    sessions: list[dict[str, object]] = []
    ends: dict[str, datetime] = {}
    for s, operator, viewed, slug in rows:
        end = s.ended_at or s.expires_at
        changes = sum(
            1
            for a in audit
            if a.action == "project.change"
            and a.via == "impersonation"
            and a.actor_id == s.target_user_id
            and (a.detail or {}).get("impersonator_id") == str(s.operator_id)
            and s.created_at <= a.at <= end
        )
        sessions.append(
            {
                "id": str(s.id),
                "operator": operator,
                "viewed_as": viewed,
                "organization": slug,
                "reason": s.reason,
                "started_at": s.created_at.isoformat(),
                "ended_at": s.ended_at.isoformat() if s.ended_at else None,
                "expired_at": s.expires_at.isoformat(),
                "writes_enabled": str(s.id) in writes_sessions,
                "changes": changes,
            }
        )
        ends[str(s.id)] = end
    lines = [f"Support access, {since:%Y-%m-%d %H:%M} to {until:%Y-%m-%d %H:%M} UTC"]
    if not sessions:
        lines.append("No support access in this period.")
    for item in sessions:
        writes = f"writes on, {item['changes']} change(s)" if item["writes_enabled"] else "read-only"
        started = _hm(datetime.fromisoformat(str(item["started_at"])))
        until_hm = _hm(ends[str(item["id"])])
        lines.append(
            f"- {started} {item['operator']} viewed as {item['viewed_as']} in {item['organization']}. "
            f'Reason: "{item["reason"]}". Until {until_hm}; {writes}.'
        )
    lines.append(
        f"{len(sessions)} session(s), {refused} refused "
        "because the organization turned support access off."
    )
    return Digest(since, until, sessions, refused, "\n".join(lines))


async def run(
    db: AsyncSession,
    settings: Settings,
    *,
    force: bool = False,
    now: datetime | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> RunResult:
    """Build and deliver the digest. The caller commits (the audit row rides on its transaction)."""
    webhook = settings.security_digest_webhook_url
    address = settings.security_digest_email
    if webhook is None and not address:
        return RunResult(sent=False, error="no_destination")
    now = now or datetime.now(UTC)
    window = timedelta(hours=settings.security_digest_hours)
    if not force:
        last = (
            await db.execute(
                select(AuditLog.at)
                .where(AuditLog.action == "impersonation.digest_sent")
                .order_by(AuditLog.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if last is not None and now - last < window * 0.9:
            return RunResult(sent=False, skipped="already_sent")
    d = await build(db, now - window, now)
    channels: list[str] = []
    failed = False
    if webhook is not None:
        try:
            async with httpx.AsyncClient(transport=transport, timeout=TIMEOUT_SECONDS) as client:
                response = await client.post(webhook.get_secret_value(), json={"text": d.text})
            if response.status_code >= 400:
                raise httpx.HTTPError("bad status")
            channels.append("webhook")
        except httpx.HTTPError as exc:
            log.warning("digest_webhook_failed", error=type(exc).__name__)  # never the URL
            failed = True
    if address:
        if await mail_service.send(address, "Support access digest", d.text):
            channels.append("email")
        else:
            failed = True
    if not channels:
        return RunResult(sent=False, error="delivery_failed", digest=d)
    await audit_service.record(
        db,
        action="impersonation.digest_sent",
        detail={"sessions": len(d.sessions), "refused": d.refused, "channels": ",".join(channels)},
    )
    return RunResult(
        sent=True, channels=channels, error="delivery_failed" if failed else None, digest=d
    )
