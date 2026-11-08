"""Create two staff accounts in the REVIEW database (never a real DB): op-admin / op-support.  Prints nothing secret."""
import asyncio
from app.core import platform_security as sec
from app.db import get_session_factory
from app.models.enums import PlatformRole
from app.models.platform import PlatformUser
from app.services.organization_service import OrganizationService

async def main():
    async with get_session_factory()() as s:
        for email, role in [("op-admin@example.com", PlatformRole.platform_admin), ("op-support@example.com", PlatformRole.platform_support)]:
            u = PlatformUser(email=email, name=email.split("@")[0], password_hash=sec.hash_password("correct-horse-battery-staple-9"), platform_role=role)
            s.add(u); await s.commit()
            await OrganizationService(s).ensure_personal_org(u); await s.commit()
asyncio.run(main())
