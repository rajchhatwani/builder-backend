"""The daily support-access digest (PLATFORM_SAAS_PLAN §4.5: "daily digest to a security channel").

Built from impersonation_sessions + the audit log; delivered to a webhook (Slack-compatible
`{"text": …}`) and/or an e-mail address; run by cron: `python -m app.jobs.impersonation_digest`.
A quiet day still sends a message, so silence means the job is broken, not that nothing happened.
"""
# ruff: noqa: F811  (the `world` fixture is imported, then used as a parameter)

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models.platform import AuditLog
from app.services import impersonation_digest as digest
from app.services import mail_service
from tests.api.test_impersonation import World, world  # noqa: F401

Factory = async_sessionmaker[AsyncSession]
HOOK = "https://hooks.example.test/services/T000/B000/SECRET-HOOK-PATH"


def _settings(**kw: object) -> Settings:
    return Settings(security_digest_webhook_url=HOOK, **kw)  # type: ignore[arg-type]


class Hook:
    def __init__(self, status: int = 200) -> None:
        self.calls: list[dict[str, object]] = []
        self.status = status

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.calls.append(
                {"url": str(request.url), "json": __import__("json").loads(request.content)}
            )
            return httpx.Response(self.status)

        return httpx.MockTransport(handle)


async def test_the_digest_lists_sessions_with_who_why_and_what_they_did(
    world: World,
    session_factory: Factory,  # noqa: F811
) -> None:
    viewer, _ = await world.view_as(reason="ticket 4411")
    await viewer.post("/account/impersonation/writes", json={"enabled": True})
    await viewer.post(f"/projects/{world.project}/entities", json={"name": "Invoice"})
    await viewer.post("/account/impersonation/end")
    await world.view_as(world.member, reason="billing page blank")
    await world.owner.patch("/orgs/acme/policies", json={"allow_impersonation": False})
    await world.ops.post(
        f"/admin/organizations/{world.org_id}/members/{world.owner.user.id}/impersonate",  # type: ignore[attr-defined]
        json={"reason": "tried anyway"},
    )
    async with session_factory() as db:
        d = await digest.build(db, datetime.now(UTC) - timedelta(hours=24), datetime.now(UTC))
    assert len(d.sessions) == 2
    first = next(s for s in d.sessions if s["reason"] == "ticket 4411")
    assert first["operator"] == "ops@example.com" and first["viewed_as"] == "owner@example.com"
    assert (
        first["organization"] == "acme"
        and first["writes_enabled"] is True
        and first["changes"] == 1
    )
    other = next(s for s in d.sessions if s["reason"] == "billing page blank")
    assert other["writes_enabled"] is False and other["changes"] == 0
    assert d.refused == 1
    for line in ("ticket 4411", "ops@example.com", "owner@example.com", "acme"):
        assert line in d.text
    assert "1 refused" in d.text


async def test_a_quiet_day_still_produces_a_message(session_factory: Factory) -> None:
    async with session_factory() as db:
        d = await digest.build(db, datetime.now(UTC) - timedelta(hours=24), datetime.now(UTC))
    assert d.sessions == [] and "No support access" in d.text


async def test_sessions_outside_the_window_are_left_out(
    world: World, session_factory: Factory
) -> None:  # noqa: F811
    await world.view_as()
    async with session_factory() as db:
        d = await digest.build(
            db, datetime.now(UTC) + timedelta(hours=1), datetime.now(UTC) + timedelta(hours=25)
        )
    assert d.sessions == []


async def test_it_posts_to_the_webhook_and_audits_without_the_url(
    world: World,
    session_factory: Factory,  # noqa: F811
) -> None:
    await world.view_as(reason="ticket 4411")
    hook = Hook()
    async with session_factory() as db:
        result = await digest.run(db, _settings(), transport=hook.transport())
        await db.commit()
    assert result.channels == ["webhook"] and result.sent
    assert len(hook.calls) == 1 and "ticket 4411" in str(hook.calls[0]["json"]["text"])  # type: ignore[index]
    async with session_factory() as db:
        rows = (
            (
                await db.execute(
                    select(AuditLog).where(AuditLog.action == "impersonation.digest_sent")
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1 and rows[0].detail["sessions"] == 1  # type: ignore[index]
    assert "SECRET-HOOK-PATH" not in repr(rows[0].detail) and rows[0].organization_id is None


async def test_it_does_not_send_twice_in_a_day_unless_forced(session_factory: Factory) -> None:
    hook = Hook()
    async with session_factory() as db:
        assert (await digest.run(db, _settings(), transport=hook.transport())).sent
        await db.commit()
    async with session_factory() as db:
        again = await digest.run(db, _settings(), transport=hook.transport())
        assert again.sent is False and again.skipped == "already_sent"
        forced = await digest.run(db, _settings(), force=True, transport=hook.transport())
        await db.commit()
    assert forced.sent and len(hook.calls) == 2


async def test_it_also_sends_email_when_an_address_is_set(
    session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[str, str, str]] = []

    async def fake(to: str, subject: str, body: str) -> bool:
        sent.append((to, subject, body))
        return True

    monkeypatch.setattr(mail_service, "send", fake)
    async with session_factory() as db:
        result = await digest.run(db, Settings(security_digest_email="security@example.com"))
        await db.commit()
    assert result.channels == ["email"] and sent[0][0] == "security@example.com"
    assert "Support access" in sent[0][1]


async def test_a_failed_delivery_is_not_recorded_as_sent(session_factory: Factory) -> None:
    hook = Hook(status=500)
    async with session_factory() as db:
        result = await digest.run(db, _settings(), transport=hook.transport())
        await db.commit()
        assert result.sent is False and result.error == "delivery_failed"
    async with session_factory() as db:
        assert (
            await digest.run(db, _settings(), transport=Hook().transport())
        ).sent  # can retry at once


async def test_nothing_configured_is_reported_not_silently_ignored(
    session_factory: Factory,
) -> None:
    async with session_factory() as db:
        result = await digest.run(db, Settings())
    assert result.sent is False and result.error == "no_destination"


async def test_the_operator_can_preview_the_digest(world: World) -> None:  # noqa: F811
    await world.view_as(reason="ticket 4411")
    r = await world.ops.get("/admin/impersonation/digest?hours=24")
    assert r.status_code == 200
    body = r.json()
    assert len(body["sessions"]) == 1 and "ticket 4411" in body["text"]
    assert (await world.owner.get("/admin/impersonation/digest")).status_code == 401


async def test_support_staff_cannot_preview_it(world: World, client_for) -> None:  # noqa: ANN001,F811
    from app.core import platform_security as sec
    from app.models.enums import PlatformRole

    support = await client_for(
        "help@example.com", PlatformRole.platform_support, audience=sec.AUDIENCE_ADMIN
    )
    assert (await support.get("/admin/impersonation/digest")).status_code == 403


_ = AsyncClient
