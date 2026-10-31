import os
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.community.postgres import PostgresContainer

from app.core import platform_security as sec
from app.db import get_session
from app.main import app
from app.models.base import Base
from app.models.enums import PlatformRole
from app.models.platform import PlatformUser


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """A throwaway Postgres. TEST_DATABASE_URL (a postgresql+asyncpg URL to an *empty,
    disposable* database) skips Docker; otherwise a container is started."""
    override = os.environ.get("TEST_DATABASE_URL")
    if override:
        yield override
        return
    with PostgresContainer("postgres:16-alpine") as container:
        yield container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")


@pytest.fixture(scope="session")
async def engine(database_url: str) -> AsyncGenerator[AsyncEngine, None]:
    eng = create_async_engine(database_url)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Seed the plans table (Phase A invariant): a Subscription row references a Plan.
    async with eng.begin() as conn:
        from sqlalchemy import text as _text

        await conn.execute(
            _text(
                """
                INSERT INTO plans (
                    id, display_name, max_seats, max_projects, max_api_tokens,
                    max_mcp_tokens, allow_sso, allow_scim, allow_mcp,
                    monthly_price_usd, is_public, created_at
                ) VALUES
                    ('free',       'Free',       1,    1,    3,   0,  false, false, false, 0,    true,  now()),
                    ('team',       'Team',       5,    10,   20,  5,  false, false, true,  2900, true,  now()),
                    ('business',   'Business',   25,   50,   100, 25, true,  false, true,  9900, true,  now()),
                    ('enterprise', 'Enterprise', NULL, NULL, NULL, NULL, true, true, true,  0,    false, now())
                ON CONFLICT (id) DO NOTHING
                """
            )
        )
    yield eng
    await eng.dispose()


_FACTORY: list[async_sessionmaker[AsyncSession]] = []


@pytest.fixture(scope="session")
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    _FACTORY[:] = [factory]  # for add_to_project_org(), which helpers call without fixtures
    return factory


@pytest.fixture(autouse=True)
async def _clean_tables(engine: AsyncEngine) -> AsyncGenerator[None, None]:
    yield
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            if table.name == "plans":
                continue  # Plans are seeded once and reused across tests.
            await conn.execute(table.delete())


async def _seed_personal_org(session: AsyncSession, user: PlatformUser) -> None:
    """Match the sign-up flow: give the user a personal org + free subscription."""
    from app.services.organization_service import OrganizationService

    await OrganizationService(session).ensure_personal_org(user)


TEST_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(autouse=True)
def _unlimited_personal_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase B enforces plan caps (free = 1 project, 0 MCP tokens). Most tests are about
    builder features, not quotas, so test users' personal orgs start on the uncapped
    'enterprise' plan. Quota tests (test_plan_enforcement.py) set the plan they need."""
    from app.services import organization_service

    monkeypatch.setattr(organization_service, "DEFAULT_PERSONAL_PLAN_ID", "enterprise")
    # New team orgs start on 'free' (1 seat) in production; feature tests that build a team
    # and invite people get the paid 'team' plan unless they set one themselves.
    monkeypatch.setattr(organization_service, "DEFAULT_TEAM_PLAN_ID", "team")


@pytest.fixture(autouse=True)
def _fast_hashing_and_fresh_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """scrypt at production cost would add ~100 ms per login to hundreds of tests."""
    from app.api import security

    monkeypatch.setattr(sec, "SCRYPT_N", 2**10)
    security.reset_auth_limiter()


@pytest.fixture
async def override_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[None, None]:
    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    yield
    app.dependency_overrides.pop(get_session, None)


MakeUser = Callable[..., Awaitable[PlatformUser]]


@pytest.fixture
def make_user(session_factory: async_sessionmaker[AsyncSession]) -> MakeUser:
    """Insert an account directly (no HTTP, no slow hashing path) and return it.

    Phase A invariant: every signed-in user has a personal org. Mirror the sign-up flow by
    seeding a personal org for each test user (on 'enterprise' in tests — see
    `_unlimited_personal_plan`).
    """

    async def make(
        email: str = "primary@example.com",
        role: PlatformRole = PlatformRole.customer,
        password: str = TEST_PASSWORD,
        **fields: object,
    ) -> PlatformUser:
        # Fixture accounts count as having proved their mailbox; sign-up through the API doesn't.
        fields.setdefault("email_verified_at", datetime.now(UTC))
        async with session_factory() as session:
            user = PlatformUser(
                email=email,
                name="Test",
                password_hash=sec.hash_password(password),
                platform_role=role,
                **fields,
            )
            session.add(user)
            await session.commit()
            # Phase A: give the user a personal org + subscription.
            await _seed_personal_org(session, user)
            await session.commit()
            await session.refresh(user)
            return user

    return make


def bearer_for(
    user: PlatformUser, audience: str = sec.AUDIENCE_APP, amr: list[str] | None = None
) -> dict[str, str]:
    """A session token. `amr` = how it was signed in, e.g. ["pwd", "otp"] (§4.4)."""
    token = sec.encode_jwt(
        sec.access_claims(
            user_id=str(user.id),
            audience=audience,
            token_version=user.token_version,
            ttl_seconds=600,
            amr=amr,
        )
    )
    return {"Authorization": f"Bearer {token}"}


ClientFor = Callable[..., Awaitable[AsyncClient]]


@pytest.fixture
async def client_for(
    override_session: None, make_user: MakeUser
) -> AsyncGenerator[ClientFor, None]:
    """Build extra signed-in clients: `await client_for("b@example.com")`."""
    opened: list[AsyncClient] = []

    async def build(
        email: str = "primary@example.com",
        role: PlatformRole = PlatformRole.customer,
        audience: str = sec.AUDIENCE_APP,
        **fields: object,
    ) -> AsyncClient:
        user = await make_user(email, role, **fields)
        # Staff sessions carry a second factor (§4.4); the admin guard checks it.
        amr = ["pwd", "otp"] if audience == sec.AUDIENCE_ADMIN else None
        c = AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers=bearer_for(user, audience, amr=amr),
        )
        c.user = user  # type: ignore[attr-defined]
        opened.append(c)
        return c

    yield build
    for c in opened:
        await c.aclose()


@pytest.fixture
async def client(client_for: ClientFor) -> AsyncClient:
    """A signed-in customer. Most tests are about the builder's features, not about access."""
    return await client_for("primary@example.com")


@pytest.fixture
async def anon_client(override_session: None) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


@pytest.fixture(autouse=True)
def _no_dev_rls(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's .env may switch RLS binding on for the local database; the suite runs
    without it unless a test asks (tests/api/test_rls.py)."""
    from app.config import get_settings

    monkeypatch.setenv("BUILDER_RLS_ENABLED", "false")
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Credentials are encrypted with SECRET_KEY, so every API test gets a fixed one."""
    import app.core.crypto as crypto

    monkeypatch.setenv("SECRET_KEY", "api-test-secret-key")
    monkeypatch.setattr(crypto, "_fernet", None)


async def add_to_project_org(project_id: object, email: str) -> None:
    """§3.2: a project member must belong to the project's org. Tests that share a project
    with another person put them in its org first (test orgs have uncapped seats)."""
    import uuid as _uuid

    from sqlalchemy import select as _select

    from app.models.enums import OrgRole
    from app.models.platform import OrganizationMember
    from app.models.project import Project

    async with _FACTORY[0]() as session:
        project = await session.get(Project, _uuid.UUID(str(project_id)))
        user = (
            await session.execute(_select(PlatformUser).where(PlatformUser.email == email.lower()))
        ).scalar_one_or_none()
        if project is None or user is None:
            return  # the test is about a missing project/user; let the API answer that
        if await session.get(OrganizationMember, (project.organization_id, user.id)) is None:
            session.add(
                OrganizationMember(
                    organization_id=project.organization_id, user_id=user.id, role=OrgRole.member
                )
            )
            await session.commit()


class TotpClock:
    """A frozen clock for TOTP checks. `code(secret)` steps 30 s forward first, so every call
    returns a code for a step the account has not used yet (codes are never accepted twice)."""

    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def time(self) -> float:
        return self.now

    def code(self, secret: str) -> str:
        from app.core import totp

        self.now += totp.PERIOD
        return totp.code_at(secret, self.now)


@pytest.fixture
def totp_clock(monkeypatch: pytest.MonkeyPatch) -> TotpClock:
    from types import SimpleNamespace

    from app.core import totp

    clock = TotpClock()
    monkeypatch.setattr(totp, "time", SimpleNamespace(time=clock.time))
    return clock
