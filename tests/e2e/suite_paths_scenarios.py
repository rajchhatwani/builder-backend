"""Scenarios for suite identity paths (b) and (c), copied into generated projects as tests/test_scenarios.py by
tests/e2e/test_suite_identity_paths_stack.py and run against a real Postgres. Each test runs in ONE role (env
E2E_ROLE) and exchanges files through E2E_OUT; the CLI steps run as the customer would (`python -m app.auth.export`).

  b_source   the OLD built-in app: users, an owned row, export, keycloak-import, impact
  b_target   the NEW suite member (dual or hub_only): import, relink --copy, legacy token vs hub token
  c_first    app one of path (c): users with verified and unverified e-mail, export
  c_second   app two: overlap analyser against app one's export, then verified linking
"""

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from app.auth import config, identity
from app.db import session_factory

ROLE = os.environ.get("E2E_ROLE", "")
OUT = Path(os.environ.get("E2E_OUT", "."))
SECRET = "legacy-signing-secret-" + "k" * 32
LEGACY_ISSUER = "builtin:suite-portal"


def cli(*args: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "app.auth.export", *args], capture_output=True, text=True, env=dict(os.environ)
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def mine(role: str) -> Any:
    return pytest.mark.skipif(ROLE != role, reason=f"role {role} only")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


async def _rows(sql: str) -> list[Any]:
    async with session_factory() as session:
        return list((await session.execute(text(sql))).mappings().all())


async def _register_unverified(client: Any, email: str, n: int) -> None:
    from tests._auth_support import registration_payload

    response = await client.post("/auth/register", json=await registration_payload(email, n))
    assert response.status_code == 201, response.text


# --- path (b), the old built-in app ---------------------------------------------------------


@mine("b_source")
async def test_b_source_exports_and_prepares_the_hub_files(client: Any, outbox: Any) -> None:
    from tests._auth_support import sign_in

    ann = await sign_in(client, "ann@example.com", roles=["agent"])
    await sign_in(client, "bob@example.com", roles=["admin"])
    await _register_unverified(client, "cy@example.com", 2)
    for subject in ("first ticket", "second ticket"):
        assert (await client.post("/tickets", headers=ann, json={"subject": subject})).status_code == 201
    users = {r["email"]: str(r["id"]) for r in await _rows("SELECT id, email FROM auth_users")}
    tickets = [
        {"id": str(r["id"]), "subject": r["subject"], "created_by_id": str(r["created_by_id"])}
        for r in await _rows("SELECT id, subject, created_by_id FROM tickets ORDER BY subject")
    ]
    hashes = [r["password_hash"] for r in await _rows("SELECT password_hash FROM auth_users")]
    assert len(hashes) == 3 and all(h.startswith("scrypt$") for h in hashes)

    OUT.mkdir(parents=True, exist_ok=True)
    cli("export", "--out", str(OUT / "users.ndjson"))
    (OUT / "hub.ndjson").write_text(
        "\n".join(
            json.dumps(r)
            for r in (
                {"email": "ANN@example.com", "email_verified": True},
                {"email": "cy@example.com", "email_verified": False},
                {"email": "hub-only@example.com", "email_verified": True},
            )
        ),
        encoding="utf-8",
    )
    cli("keycloak-import", "--out", str(OUT / "kc.json"))
    cli("impact", "--hub-users", str(OUT / "hub.ndjson"), "--out", str(OUT / "impact.json"))
    # The old app's access token, signed with its own secret: it must keep working in the new app.
    from tests._auth_support import bearer

    token = ann["Authorization"].split()[1]
    old_secret = config.get_auth_settings().jwt_key
    (OUT / "state.json").write_text(
        json.dumps(
            {"users": users, "tickets": tickets, "hashes": hashes, "ann_token": token, "legacy_secret": old_secret}
        ),
        encoding="utf-8",
    )
    del bearer


# --- path (b), the new suite member -----------------------------------------------------------


def _legacy_token(secret: str, sub: str, **claims: Any) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {"iss": LEGACY_ISSUER, "sub": sub, "type": "access", "iat": now, "exp": now + 600}
    payload.update(claims)
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest())
    return f"{head}.{body}.{sig}"


@mine("b_target")
async def test_b_target_serves_legacy_and_hub_tokens_as_the_same_user(
    client: Any, key_server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.auth import legacy
    from tests._auth_support import bearer, token

    state = json.loads((OUT / "state.json").read_text(encoding="utf-8"))
    expect = os.environ["E2E_EXPECT"]  # dual | hub_only
    monkeypatch.setenv("LEGACY_JWT_SECRET", state["legacy_secret"])
    hub_issuer = config.get_auth_settings().issuer

    # 1. the identity-v1 file moves the accounts; local ids stay what they were
    counts = json.loads(cli("import", str(OUT / "users.ndjson")))
    assert counts["user"] == 3 and counts["identity"] == 3
    assert json.loads(cli("import", str(OUT / "users.ndjson")))["user"] == 0  # running twice changes nothing
    ids = {r["email"]: str(r["id"]) for r in await _rows("SELECT id, email FROM auth_users")}
    assert ids == state["users"]
    # 2. the owned rows keep created_by_id (the data migration is the customer's; the ids are the contract)
    async with session_factory() as session:
        for t in state["tickets"]:
            await session.execute(
                text("INSERT INTO tickets (id, subject, created_by_id, created_at, updated_at) "
                     "VALUES (:id, :s, :c, now(), now())"),
                {"id": t["id"], "s": t["subject"], "c": t["created_by_id"]},
            )
        await session.commit()
    # 3. the hub identities are copies of the old ones (same subjects = the Keycloak ids kc.json created)
    assert json.loads(cli("relink", "--from", LEGACY_ISSUER, "--to", hub_issuer, "--copy"))["relinked"] == 3
    ann = ids["ann@example.com"]

    old = bearer(state["ann_token"])  # a token the OLD app issued
    hub = bearer(token(sub=ann, email="ann@example.com", roles=["agent"]))
    via_hub = await client.get("/auth/me", headers=hub)
    assert via_hub.status_code == 200, via_hub.text
    assert via_hub.json()["id"] == ann
    if expect == "dual":
        via_old = await client.get("/auth/me", headers=old)
        assert via_old.status_code == 200, via_old.text
        assert via_old.json()["id"] == ann  # the SAME local user
        for headers in (old, hub):
            listed = await client.get("/tickets", headers=headers)
            assert listed.status_code == 200
            assert {t["subject"] for t in listed.json()["items"]} == {"first ticket", "second ticket"}
        rows = await _rows("SELECT created_by_id FROM tickets")
        assert {str(r["created_by_id"]) for r in rows} == {ann}  # created_by_id unchanged
        # (iss, sub) stays unique
        dup = await _rows(
            "SELECT issuer, subject, count(*) AS n FROM auth_identities GROUP BY issuer, subject HAVING count(*) > 1"
        )
        assert dup == []
        # an unknown legacy subject is never turned into a user
        stranger = bearer(_legacy_token(state["legacy_secret"], str(uuid.uuid4())))
        assert (await client.get("/auth/me", headers=stranger)).status_code == 401
        # the window ends: legacy tokens stop, the hub token keeps working (fails closed)
        end = legacy.window_end()
        assert end is not None
        monkeypatch.setattr(legacy, "_now", lambda: end + dt.timedelta(seconds=1))
        assert (await client.get("/auth/me", headers=old)).status_code == 401
        assert (await client.get("/auth/me", headers=hub)).status_code == 200
        # forward to hub_only in the same process: both legacy credential kinds are refused
        monkeypatch.setattr(legacy, "_now", lambda: end - dt.timedelta(days=1))
        assert (await client.get("/auth/me", headers=old)).status_code == 200
        monkeypatch.setattr(config, "LEGACY_STATE", "hub_only")
    assert (await client.get("/auth/me", headers=old)).status_code == 401
    assert (await client.get("/auth/me", headers=hub)).status_code == 200
    for kind in ("access", "refresh"):
        assert legacy.refusal("GET", kind) is not None
    del key_server


# --- path (c): two independent apps ----------------------------------------------------------


@mine("c_first")
async def test_c_first_exports_its_accounts(client: Any, outbox: Any) -> None:
    from tests._auth_support import sign_in

    await sign_in(client, "shared@example.com", roles=["agent"])
    await sign_in(client, "only-first@example.com")
    await _register_unverified(client, "pending@example.com", 3)
    OUT.mkdir(parents=True, exist_ok=True)
    cli("export", "--out", str(OUT / "first.ndjson"))
    ids = {r["email"]: str(r["id"]) for r in await _rows("SELECT id, email FROM auth_users")}
    issuer = config.current_issuer()
    (OUT / "first.json").write_text(json.dumps({"ids": ids, "issuer": issuer}), encoding="utf-8")


@mine("c_second")
async def test_c_second_finds_exactly_the_verified_overlap_and_links_only_with_both_proofs(
    client: Any, outbox: Any
) -> None:
    from tests._auth_support import sign_in

    first = json.loads((OUT / "first.json").read_text(encoding="utf-8"))
    await sign_in(client, "shared@example.com", roles=["admin"])
    await sign_in(client, "only-second@example.com")
    await _register_unverified(client, "pending@example.com", 4)  # unverified on BOTH sides
    ids = {r["email"]: str(r["id"]) for r in await _rows("SELECT id, email FROM auth_users")}
    before = await _rows("SELECT id, email, roles FROM auth_users ORDER BY id")

    cli("overlap", "--other", str(OUT / "first.ndjson"), "--out", str(OUT / "overlap.json"))
    report = json.loads((OUT / "overlap.json").read_text(encoding="utf-8"))
    assert [c["email"] for c in report["collisions"]] == ["shared@example.com"]  # exactly the verified one
    assert report["collisions"][0]["mine"] == [ids["shared@example.com"]]
    assert report["collisions"][0]["other"] == [first["ids"]["shared@example.com"]]
    assert report["role_conflicts"][0]["only_mine"] == ["admin"]
    assert report["unverified"]["same_address_on_both_sides"] == ["pending@example.com"]
    assert report["modified"] is False
    assert await _rows("SELECT id, email, roles FROM auth_users ORDER BY id") == before  # the dry run changed nothing
    raw = (OUT / "overlap.json").read_text(encoding="utf-8")
    assert "scrypt$" not in raw and "password" not in raw

    mine_id = uuid.UUID(ids["shared@example.com"])
    own = config.current_issuer()
    a = {"iss": own, "sub": str(mine_id), "email": "shared@example.com", "email_verified": True}
    b = {"iss": first["issuer"], "sub": first["ids"]["shared@example.com"], "email": "shared@example.com",
         "email_verified": True}
    trusted = {own, first["issuer"]}

    async def link(a_claims: dict[str, Any], b_claims: dict[str, Any], who: Any = trusted, user: uuid.UUID = mine_id) -> bool:
        async with session_factory() as session:
            return await identity.link_verified(session, user, a_claims, b_claims, who)

    # refused: untrusted issuer, one side unverified, e-mail-only (an unverified address), wrong account
    with pytest.raises(identity.LinkRefused):
        await link(a, b, {own})
    with pytest.raises(identity.LinkRefused):
        await link(a, {**b, "email_verified": False})
    with pytest.raises(identity.LinkRefused):
        await link({**a, "email_verified": False}, b)
    pending = uuid.UUID(ids["pending@example.com"])
    with pytest.raises(identity.LinkRefused):
        await link(
            {"iss": own, "sub": str(pending), "email": "pending@example.com", "email_verified": False},
            {"iss": first["issuer"], "sub": first["ids"]["pending@example.com"], "email": "pending@example.com",
             "email_verified": False},
            user=pending,
        )
    with pytest.raises(identity.LinkRefused):  # proof A is not this user's identity
        await link(a, b, user=pending)
    foreign = await _rows(f"SELECT count(*) AS n FROM auth_identities WHERE issuer = '{first['issuer']}'")
    assert foreign[0]["n"] == 0  # every refusal left the database alone
    # both proofs, trusted issuers: linked, once; the local id is unchanged
    assert await link(a, b) is True
    assert await link(a, b) is False
    async with session_factory() as session:
        assert await identity.find_user_id(session, first["issuer"], b["sub"]) == mine_id
    assert await _rows("SELECT id, email, roles FROM auth_users ORDER BY id") == before
