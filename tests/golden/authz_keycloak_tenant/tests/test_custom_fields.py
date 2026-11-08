"""Custom registration fields (generated): Keycloak keeps them as user attributes and delivers
them as token claims; the API copies them to auth_users, typed and checked."""

import datetime as dt
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.auth import config, oidc
from app.auth.models import AuthUser
from app.db import session_factory
from tests._auth_support import bearer, token

pytestmark = pytest.mark.usefixtures("outbox")

# A valid value for every field.
SAMPLES = {'age': 13, 'born': '2000-01-31', 'company': 'xxxxxx', 'mobile': '+14155550100', 'newsletter': True, 'notes': 'xxxxxx', 'plan': 'free', 'score': 0, 'site': 'https://example.com/sample'}


async def test_values_in_the_token_are_stored_and_returned(client: AsyncClient) -> None:
    response = await client.get("/auth/me", headers=bearer(token(**SAMPLES)))

    assert response.status_code == 200, response.text
    body = response.json()
    for name in SAMPLES:
        assert body[name] is not None, name
    assert body["age"] == SAMPLES["age"]
    assert body["company"] == SAMPLES["company"]
    assert body["mobile"] == SAMPLES["mobile"]
    assert body["newsletter"] == SAMPLES["newsletter"]
    assert body["notes"] == SAMPLES["notes"]
    assert body["plan"] == SAMPLES["plan"]
    assert body["score"] == SAMPLES["score"]
    assert body["site"] == SAMPLES["site"]


async def test_fields_follow_keycloak_when_they_change(client: AsyncClient) -> None:
    sub = uuid.uuid4()
    await client.get("/auth/me", headers=bearer(token(sub=sub, **SAMPLES)))
    n = 1  # the value of age for a different sample
    changed = {"age": 13 + n}
    await client.get("/auth/me", headers=bearer(token(sub=sub, **changed)))
    async with session_factory() as session:
        row = await session.get(AuthUser, sub)
    assert row is not None
    assert row.age == changed["age"]


async def test_a_field_missing_from_a_later_token_is_kept(client: AsyncClient) -> None:
    sub = uuid.uuid4()
    await client.get("/auth/me", headers=bearer(token(sub=sub, **SAMPLES)))

    later = await client.get("/auth/me", headers=bearer(token(sub=sub)))

    for name in SAMPLES:
        assert later.json()[name] is not None, name


async def test_values_that_do_not_fit_are_stored_as_nothing(client: AsyncClient) -> None:
    """A claim that is the wrong kind of value (an object here) never breaks the request or a
    column: it is simply not stored."""
    junk = {name: {"not": "valid"} for name in SAMPLES}

    response = await client.get("/auth/me", headers=bearer(token(**junk)))

    assert response.status_code == 200, response.text
    for name in SAMPLES:
        assert response.json()[name] is None, name


async def test_claims_that_are_not_configured_fields_are_ignored(client: AsyncClient) -> None:
    response = await client.get("/auth/me", headers=bearer(token(favourite_colour="blue", **SAMPLES)))

    assert response.status_code == 200
    assert "favourite_colour" not in response.json()
    assert "favourite_colour" not in [f[0] for f in config.CUSTOM_FIELDS]


async def test_text_longer_than_its_column_is_not_stored(client: AsyncClient) -> None:
    too_long = {"company": "x" * (80 + 1)}

    response = await client.get("/auth/me", headers=bearer(token(**too_long)))

    assert response.status_code == 200, response.text
    assert response.json()["company"] is None


async def test_deleting_the_account_erases_the_fields(client: AsyncClient) -> None:
    sub = uuid.uuid4()
    access = token(sub=sub, **SAMPLES)
    await client.get("/auth/me", headers=bearer(access))

    assert (await client.delete("/auth/me", headers=bearer(access))).status_code == 204

    async with session_factory() as session:
        row = (await session.execute(select(AuthUser).where(AuthUser.id == sub))).scalar_one()
    for name in SAMPLES:
        assert getattr(row, name) is None, name


@pytest.mark.parametrize(
    ("kind", "value", "expected"),
    [
        ("integer", "42", 42),
        ("integer", True, None),
        ("integer", "4.2", None),
        ("integer", "9" * 40, None),
        ("float", "7.5", 7.5),
        ("float", "nan", None),
        ("float", True, None),
        ("boolean", "true", True),
        ("boolean", "yes", None),
        ("date", "2000-01-31", dt.date(2000, 1, 31)),
        ("date", "31/01/2000", None),
        ("enum", "other", None),
        ("string", ["one"], "one"),
        ("string", ["one", "two"], None),
        ("string", "a\x00b", None),
    ],
)
def test_coercion_rules(kind: str, value: object, expected: object) -> None:
    assert oidc.coerce_attribute(kind, value, 10, ("free", "pro")) == expected
