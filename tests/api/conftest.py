import os
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterator

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


@pytest.fixture(scope="session")
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


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


def bearer_for(user: PlatformUser, audience: str = sec.AUDIENCE_APP) -> dict[str, str]:
    token = sec.encode_jwt(
        sec.access_claims(
            user_id=str(user.id),
            audience=audience,
            token_version=user.token_version,
            ttl_seconds=600,
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
        c = AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers=bearer_for(user, audience),
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
def _secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Credentials are encrypted with SECRET_KEY, so every API test gets a fixed one."""
    import app.core.crypto as crypto

    monkeypatch.setenv("SECRET_KEY", "api-test-secret-key")
    monkeypatch.setattr(crypto, "_fernet", None)
