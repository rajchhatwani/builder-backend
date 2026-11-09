"""P6: reencrypt_all moves stored ciphertext (all four tables) to the active key."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core import crypto
from app.core.key_provider import FakeKms
from tests.api._auth_helpers import make_project


@pytest.fixture
def kms() -> FakeKms:
    k = FakeKms("k1")
    crypto.configure(k)
    yield k  # type: ignore[misc]
    crypto.reset()


async def test_reencrypt_all_rotates_every_ciphertext_column(
    client, engine: AsyncEngine, kms: FakeKms  # type: ignore[no-untyped-def]
) -> None:
    pid = await make_project(client)
    r = await client.put(f"/projects/{pid}/auth/secrets", json={"smtp": {"password": "pw-one"}})
    assert r.status_code in (200, 201, 204), r.text
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        before = (await s.execute(text("SELECT smtp_password FROM project_auth_secrets"))).scalar_one()
        assert before.startswith("v2:k1:")
        # a legacy un-prefixed value and a bytes column, written straight into the tables
        await s.execute(
            text("UPDATE project_auth_secrets SET smtp_username = :v"),
            {"v": crypto.encrypt("user")},
        )
        await s.commit()
    kms.rotate("k2")
    crypto.configure(kms)
    async with factory() as s:
        done = await crypto.reencrypt_all(s)
        await s.commit()
    assert done["project_auth_secrets.smtp_password"] == 1
    assert done["project_auth_secrets.smtp_username"] == 1
    async with factory() as s:
        row = (
            await s.execute(text("SELECT smtp_password, smtp_username FROM project_auth_secrets"))
        ).one()
        assert row[0].startswith("v2:k2:") and row[1].startswith("v2:k2:")
        assert crypto.decrypt(row[0]) == "pw-one" and crypto.decrypt(row[1]) == "user"
        again = await crypto.reencrypt_all(s)
        assert sum(again.values()) == 0  # idempotent
    kms.drop("k1")
    crypto.configure(kms)  # the old key may now be retired: nothing depends on it
    assert crypto.decrypt(row[0]) == "pw-one"
    assert uuid.UUID(pid)
