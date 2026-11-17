"""Audit B1-009: ownership transfer re-reads the owner set under lock (F-0962); parallel wrong
MFA codes still trip the lockout (F-0963)."""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.core import crypto
from app.exceptions import AppError
from app.models.enums import OrgRole, TokenAudience
from app.models.platform import Organization, OrganizationMember, PlatformUser
from app.services.mfa_service import MfaService
from app.services.organization_service import OrganizationService
from app.services.platform_auth_service import PlatformAuthService, RequestInfo
from tests.api.conftest import MakeUser

Factory = async_sessionmaker[AsyncSession]


async def test_transfer_ownership_refuses_a_concurrently_demoted_owner(
    session_factory: Factory, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-0962: A is demoted (committed by B) after A's transfer read role=owner; the transfer
    must re-check under the owner lock and refuse instead of promoting C."""
    a = await make_user("a@example.com")
    c = await make_user("c@example.com")
    async with session_factory() as s:
        org = Organization(name="Acme", slug="acme-b1009")
        s.add(org)
        await s.flush()
        org_id = org.id
        s.add(OrganizationMember(organization_id=org_id, user_id=a.id, role=OrgRole.owner))
        s.add(OrganizationMember(organization_id=org_id, user_id=c.id, role=OrgRole.member))
        await s.commit()

    real_lock = OrganizationService.lock_owners

    async def demote_then_lock(self: OrganizationService, organization_id: uuid.UUID):  # type: ignore[no-untyped-def]
        async with session_factory() as other:  # owner B's committed demotion of A
            await other.execute(
                update(OrganizationMember)
                .where(
                    OrganizationMember.organization_id == org_id,
                    OrganizationMember.user_id == a.id,
                )
                .values(role=OrgRole.member)
            )
            await other.commit()
        return await real_lock(self, organization_id)

    monkeypatch.setattr(OrganizationService, "lock_owners", demote_then_lock)
    async with session_factory() as db:
        with pytest.raises(AppError) as exc:
            await OrganizationService(db).transfer_ownership(org_id, a.id, c.id)
        assert exc.value.status_code == 403
    async with session_factory() as db:
        rows = {
            m.user_id: m.role
            for m in (
                await db.execute(
                    OrganizationMember.__table__.select().where(
                        OrganizationMember.organization_id == org_id
                    )
                )
            ).all()
        }
    assert rows[c.id] is OrgRole.member and rows[a.id] is OrgRole.member


async def test_parallel_wrong_mfa_codes_trip_the_lockout(
    session_factory: Factory, make_user: MakeUser
) -> None:
    """F-0963: N parallel wrong TOTP codes must each count toward the lockout."""
    from app.core import totp

    secret = totp.new_secret()
    user = await make_user(
        "mfa@example.com", totp_enabled_at=datetime.now(UTC), totp_secret_enc=crypto.encrypt(secret)
    )
    settings = Settings(environment="test", login_max_failures=4, lockout_minutes=15)
    async with session_factory() as db:
        row = await db.get(PlatformUser, user.id)
        assert row is not None
        token = (
            PlatformAuthService(db, settings).mfa_challenge(row, TokenAudience.app, "verify").token
        )

    async def guess() -> None:
        async with session_factory() as db:
            with pytest.raises(AppError):
                await MfaService(db, settings).verify_login(
                    mfa_token=token, code="000000", audience=TokenAudience.app, info=RequestInfo()
                )

    await asyncio.gather(*(guess() for _ in range(4)))
    async with session_factory() as db:
        row = await db.get(PlatformUser, user.id)
        assert row is not None
        assert row.locked_until is not None, f"lost updates: failed_logins={row.failed_logins}"
