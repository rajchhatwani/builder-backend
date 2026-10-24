"""M5 proof, part 2 (PLAN.md section 1 steps 3-5): download the Blog zip from the builder API,
unzip it, `docker compose up`, drive the generated API over HTTP, and run the project's own
smoke tests with `make test`'s command. Skipped when `docker compose` is unavailable.
"""

import io
import os
import shutil
import socket
import subprocess
import time
import uuid
import zipfile
from collections.abc import AsyncGenerator, Iterator
from pathlib import Path

import httpx
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
from app.models.platform import PlatformUser
from tests.api.test_spec import build_blog


def docker_compose_available() -> bool:
    if shutil.which("docker") is None:
        return False
    result = subprocess.run(["docker", "compose", "version"], capture_output=True)
    return result.returncode == 0


pytestmark = pytest.mark.skipif(
    not docker_compose_available(), reason="docker compose is not available"
)


def compose(
    root: Path, project: str, *args: str, port: int, timeout: int = 900
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "API_PORT": str(port)}
    return subprocess.run(
        ["docker", "compose", "-p", project, *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# --- builder app wired to a throwaway Postgres (same approach as tests/api) ---------------


@pytest.fixture(scope="module")
def builder_postgres() -> Iterator[PostgresContainer]:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture(scope="module")
async def builder_engine(builder_postgres: PostgresContainer) -> AsyncGenerator[AsyncEngine, None]:
    url = builder_postgres.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def builder(builder_engine: AsyncEngine) -> AsyncGenerator[AsyncClient, None]:
    factory = async_sessionmaker(builder_engine, expire_on_commit=False)

    async def override() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override
    # The builder requires sign-in: create an account directly and use its access token.
    os.environ.setdefault("SECRET_KEY", "e2e-test-secret-key")
    async with factory() as session:
        user = PlatformUser(
            email="e2e@example.com",
            name="E2E",
            password_hash=sec.hash_password("unused-password-1"),
        )
        session.add(user)
        await session.commit()
    token = sec.encode_jwt(
        sec.access_claims(
            user_id=str(user.id),
            audience=sec.AUDIENCE_APP,
            token_version=0,
            ttl_seconds=3600,
        )
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://builder",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client
    app.dependency_overrides.pop(get_session, None)


# --- the demo ---------------------------------------------------------------------------


def wait_until_healthy(base_url: str, deadline: float) -> None:
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{base_url}/ready", timeout=3).status_code == 200:
                return
        except httpx.HTTPError as exc:
            last = exc
        time.sleep(2)
    raise AssertionError(f"generated API never became ready: {last}")


def crud_flow(base_url: str) -> None:
    """Exercises what the generated smoke tests don't: relations, filters, search, errors."""
    with httpx.Client(base_url=base_url, timeout=30) as api:
        email = f"{uuid.uuid4().hex[:8]}@example.com"
        user = api.post("/users", json={"email": email, "display_name": "Ada"})
        assert user.status_code == 201, user.text
        user_id = user.json()["id"]
        assert user.json()["role"] == "member"  # spec default
        assert user.json()["posts"] == []

        tag = api.post("/tags", json={"name": f"t{uuid.uuid4().hex[:6]}"}).json()
        post = api.post(
            "/posts",
            json={
                "title": "Hello",
                "body": "First post",
                "author_id": user_id,
                "tags": [tag["id"]],
            },
        )
        assert post.status_code == 201, post.text
        post_body = post.json()
        assert post_body["author_id"] == user_id
        assert post_body["tags"] == [tag["id"]]
        assert post_body["published"] is False and post_body["views"] == 0

        # relation ids are visible from both sides
        assert api.get(f"/users/{user_id}").json()["posts"] == [post_body["id"]]
        assert api.get(f"/tags/{tag['id']}").json()["posts"] == [post_body["id"]]

        comment = api.post("/comments", json={"body": "Nice", "post_id": post_body["id"]})
        assert comment.status_code == 201, comment.text
        assert api.get(f"/posts/{post_body['id']}").json()["comments"] == [comment.json()["id"]]

        # list: pagination, filter, search, sort
        listing = api.get("/posts", params={"limit": 1, "published": "false", "q": "first"})
        assert listing.status_code == 200
        assert listing.json()["total"] == 1 and len(listing.json()["items"]) == 1
        assert api.get("/posts", params={"published": "true"}).json()["total"] == 0
        assert api.get("/posts", params={"sort": "-title,created_at"}).status_code == 200
        assert api.get("/posts", params={"sort": "body"}).status_code == 422
        assert api.get("/posts", params={"limit": 0}).status_code == 422

        # PATCH, PUT, HEAD
        patched = api.patch(f"/posts/{post_body['id']}", json={"published": True, "views": 3})
        assert patched.status_code == 200 and patched.json()["published"] is True
        assert api.patch(f"/posts/{post_body['id']}", json={"title": None}).status_code == 422
        replaced = api.put(
            f"/posts/{post_body['id']}",
            json={"title": "Replaced", "body": "x", "author_id": user_id, "tags": []},
        )
        assert replaced.status_code == 200, replaced.text
        assert replaced.json()["tags"] == [] and replaced.json()["views"] == 0
        assert api.head(f"/posts/{post_body['id']}").status_code == 200
        assert api.head(f"/posts/{uuid.uuid4()}").status_code == 404

        # error envelope
        bad_ref = api.post(
            "/posts", json={"title": "t", "body": "b", "author_id": str(uuid.uuid4())}
        )
        assert bad_ref.status_code == 422 and bad_ref.json()["code"] == "invalid_reference"
        duplicate = api.post("/users", json={"email": email, "display_name": "Again"})
        assert duplicate.status_code == 409 and duplicate.json()["code"] == "conflict"
        missing = api.get(f"/posts/{uuid.uuid4()}")
        assert missing.status_code == 404 and missing.json()["code"] == "not_found"
        invalid = api.post("/users", json={"email": email})
        assert invalid.status_code == 422 and invalid.json()["code"] == "validation_error"

        # delete: cascade from user removes posts and their comments
        assert api.delete(f"/users/{user_id}").status_code == 204
        assert api.get(f"/posts/{post_body['id']}").status_code == 404
        assert api.get(f"/comments/{comment.json()['id']}").status_code == 404
        assert api.get(f"/tags/{tag['id']}").json()["posts"] == []


async def test_blog_demo_from_download_to_running_stack(
    builder: AsyncClient, tmp_path: Path
) -> None:
    # 1-2. build the Blog model through the API and validate it
    project_id = await build_blog(builder, slug="blog")
    assert (await builder.post(f"/projects/{project_id}/validate")).json()["valid"] is True

    # 3. download the zip and unzip it
    download = await builder.get(f"/projects/{project_id}/generate/download")
    assert download.status_code == 200
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        archive.extractall(tmp_path)
    root = tmp_path / "blog"
    assert (root / "docker-compose.yml").is_file()

    # 4. docker compose up: Postgres + API, migration applied on start
    port = free_port()
    project = f"e2e{uuid.uuid4().hex[:8]}"
    try:
        up = compose(root, project, "up", "-d", "--build", "--wait", port=port)
        assert up.returncode == 0, up.stdout + up.stderr
        base_url = f"http://127.0.0.1:{port}"
        wait_until_healthy(base_url, time.monotonic() + 120)
        assert httpx.get(f"{base_url}/docs").status_code == 200
        crud_flow(base_url)

        # 5. the generated project's own smoke tests, via the command `make test` runs
        tests = compose(
            root,
            project,
            "run",
            "--rm",
            "-e",
            "DATABASE_URL=postgresql+asyncpg://app:app@db:5432/app_test",
            "api",
            "sh",
            "-c",
            "python -m tests._prepare_db && alembic upgrade head && pytest -q",
            port=port,
        )
        assert tests.returncode == 0, tests.stdout + tests.stderr
        assert "passed" in tests.stdout
    finally:
        compose(root, project, "down", "-v", "--remove-orphans", port=port, timeout=300)
