"""Suite identity path (b), builder side: the join impact report and the migration state routes."""

from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient

from app.core.suite_migration import scan_sub_readers
from app.services.suite_migration_service import SuiteMigrationService
from tests.api._auth_helpers import make_auth, make_project, make_role
from tests.api.conftest import ClientFor, add_to_project_org

_NOW = datetime.now(UTC).replace(microsecond=0)
START = _NOW.isoformat().replace("+00:00", "Z")
END = (_NOW + timedelta(days=45)).isoformat().replace("+00:00", "Z")
LEGACY = "builtin:shop"


async def _suite_project(client: AsyncClient, name: str = "Shop") -> str:
    """A project with auth, in suite `acme`, on Keycloak (a member's realm is derived)."""
    pid = await make_project(client, name)
    await make_auth(client, pid)
    await make_role(client, pid, "admin")
    suite = {"suite_id": "acme", "hub_issuer": "https://id.acme.com/realms/suite-acme"}
    assert (await client.patch(f"/projects/{pid}/auth", json={"suite": suite})).status_code == 200
    put = await client.put(
        f"/projects/{pid}/keycloak",
        json={"mode": "shared", "realm": "suite-acme", "redirect_uris": ["http://localhost:3000/"]},
    )
    assert put.status_code == 200, put.text
    enabled = await client.post(f"/projects/{pid}/keycloak/enable", json={"confirm": True})
    assert enabled.status_code == 200, enabled.text
    return pid


def body(state: str, **extra: Any) -> dict[str, Any]:
    return {"state": state, "legacy_issuer": LEGACY, **extra}


DUAL = {"dual_until": END, "window_started_at": START}


async def test_migration_moves_forward_one_step_at_a_time_and_hub_only_is_final(
    client: AsyncClient,
) -> None:
    pid = await _suite_project(client)
    url = f"/projects/{pid}/suite/migration"
    skip = await client.put(url, json=body("dual", **DUAL))  # none -> dual skips a step
    assert skip.status_code == 409 and "one step at a time" in skip.text, skip.text
    first = await client.put(url, json=body("legacy_read_only"))
    assert first.status_code == 200, first.text
    assert first.json()["join_state"] == "planned"
    assert (await client.put(url, json=body("hub_only"))).status_code == 409  # skips dual
    dual = await client.put(url, json=body("dual", **DUAL))
    assert dual.status_code == 200, dual.text
    assert dual.json()["join_state"] == "joined"
    back = await client.put(url, json=body("legacy_read_only"))
    assert back.status_code == 409 and "cannot go back" in back.text
    final = await client.put(url, json=body("hub_only"))
    assert final.status_code == 200, final.text
    for state in ("legacy_read_only", "dual"):
        again = await client.put(url, json=body(state, **(DUAL if state == "dual" else {})))
        assert again.status_code == 409, (state, again.text)
    suite = (await client.get(f"/projects/{pid}/auth")).json()["suite"]
    assert suite["migration"]["state"] == "hub_only"
    assert suite["migration"]["dual_until"] is None  # a closed migration carries no window


async def test_a_dual_window_must_be_explicit_and_at_most_90_days(client: AsyncClient) -> None:
    pid = await _suite_project(client)
    url = f"/projects/{pid}/suite/migration"
    assert (await client.put(url, json=body("legacy_read_only"))).status_code == 200
    assert (await client.put(url, json=body("dual"))).status_code == 422  # no "now" default
    assert (await client.put(url, json=body("dual", dual_until=END))).status_code == 422
    too_long = {"window_started_at": START, "dual_until": "2027-03-15T00:00:00Z"}
    assert (await client.put(url, json=body("dual", **too_long))).status_code == 422
    naive = {"window_started_at": "2026-12-01T00:00:00", "dual_until": "2026-12-20T00:00:00"}
    assert (await client.put(url, json=body("dual", **naive))).status_code == 422
    backwards = {"window_started_at": END, "dual_until": START}
    assert (await client.put(url, json=body("dual", **backwards))).status_code == 422
    stale = await client.put(url, json=body("legacy_read_only", **DUAL))
    assert stale.status_code == 422  # only dual has a window
    assert (await client.put(url, json=body("dual", **DUAL))).status_code == 200


async def test_migration_needs_a_suite_and_keycloak(client: AsyncClient) -> None:
    pid = await make_project(client)
    await make_auth(client, pid)
    url = f"/projects/{pid}/suite/migration"
    no_suite = await client.put(url, json=body("legacy_read_only"))
    assert no_suite.status_code == 409
    suite = {"suite_id": "acme", "hub_issuer": None}
    await client.patch(f"/projects/{pid}/auth", json={"suite": suite})
    builtin = await client.put(url, json=body("legacy_read_only"))
    assert builtin.status_code == 422, builtin.text  # a migration needs auth.provider keycloak
    assert (await client.get(f"/projects/{pid}/auth")).json()["suite"].get("migration") is None


async def test_the_legacy_issuer_cannot_change_once_open(client: AsyncClient) -> None:
    pid = await _suite_project(client)
    url = f"/projects/{pid}/suite/migration"
    assert (await client.put(url, json=body("legacy_read_only"))).status_code == 200
    other = await client.put(url, json={"state": "dual", "legacy_issuer": "builtin:other", **DUAL})
    assert other.status_code == 409


async def test_a_viewer_reads_but_cannot_write(client: AsyncClient, client_for: ClientFor) -> None:
    pid = await _suite_project(client)
    await add_to_project_org(pid, "ed@example.com")
    ed = await client_for("ed@example.com")
    await add_to_project_org(pid, "ed@example.com")
    await add_to_project_org(pid, "vi@example.com")
    vi = await client_for("vi@example.com")
    await add_to_project_org(pid, "vi@example.com")
    assert (await client.post(f"/projects/{pid}/members", json={"email": "vi@example.com", "role": "viewer"})).status_code == 201
    assert (await client.post(f"/projects/{pid}/members", json={"email": "ed@example.com", "role": "editor"})).status_code == 201
    assert (await vi.get(f"/projects/{pid}/suite/join/impact")).status_code == 200
    denied = await vi.put(f"/projects/{pid}/suite/migration", json=body("legacy_read_only"))
    assert denied.status_code == 403
    assert (await ed.put(f"/projects/{pid}/suite/migration", json=body("legacy_read_only"))).status_code == 200
    stranger = await client_for("eve@example.com")
    assert (await stranger.get(f"/projects/{pid}/suite/join/impact")).status_code == 404


async def test_the_impact_report_maps_roles_client_realm_and_steps(client: AsyncClient) -> None:
    pid = await _suite_project(client, "Shop Floor")
    report = (await client.get(f"/projects/{pid}/suite/join/impact")).json()
    assert report["current_provider"] == "keycloak"
    assert report["realm"] == "suite-acme" and report["client_id"] == "shop-floor"
    assert report["roles_to_client_roles"] == [
        {"role": "admin", "client_role": "admin", "client_id": "shop-floor"}
    ]
    assert [s["order"] for s in report["steps"]] == sorted(s["order"] for s in report["steps"])
    assert any("keycloak-import" in c for c in report["commands"])
    assert any("relink" in c for c in report["commands"])
    codes = {w["code"] for w in report["warnings"]}
    assert {"passwords_not_moved", "hooks_not_scanned"} <= codes
    assert report["blockers"] == []


async def test_the_impact_report_has_blockers_without_a_suite(client: AsyncClient) -> None:
    pid = await make_project(client)
    await make_auth(client, pid)
    report = (await client.get(f"/projects/{pid}/suite/join/impact")).json()
    assert report["current_provider"] == "builtin"
    assert "no_suite" in {b["code"] for b in report["blockers"]}


async def test_the_impact_lists_hooks_that_read_claims_sub(
    client: AsyncClient, monkeypatch: Any
) -> None:
    pid = await _suite_project(client)
    sources = {
        "app/hooks/orders.py": 'def before_save(ctx):\n    owner = claims["sub"]\n    return owner\n',
        "app/custom/x.py": "def ok(principal):\n    return principal.user_id\n",
        "app/hooks/b.py": "who = token.get('sub')\n",
    }

    async def fake(self: Any, project_id: Any, workspace_id: Any) -> dict[str, str]:
        return sources

    monkeypatch.setattr(SuiteMigrationService, "_load_sources", fake)
    ws = "00000000-0000-0000-0000-000000000001"
    report = (await client.get(f"/projects/{pid}/suite/join/impact?workspace_id={ws}")).json()
    assert report["hooks_scanned"] is True
    found = {(r["path"], r["line"]) for r in report["claims_sub_readers"]}
    assert found == {("app/hooks/orders.py", 2), ("app/hooks/b.py", 1)}
    assert "reads_claims_sub" in {w["code"] for w in report["warnings"]}


def test_the_scanner_ignores_other_claims_and_comments_do_not_hide_reads() -> None:
    found = scan_sub_readers(
        {"a.py": 'x = claims["email"]\ny = claims[ "sub" ]  # reads sub\nz = c.get("subscription")\n'}
    )
    assert [(f.path, f.line) for f in found] == [("a.py", 2)]


async def test_patch_auth_cannot_skip_reopen_or_extend_the_migration(client: AsyncClient) -> None:
    pid = await _suite_project(client)
    suite = {"suite_id": "acme", "hub_issuer": "https://id.acme.com/realms/suite-acme"}

    async def patch(migration: dict[str, Any]) -> Any:
        return await client.patch(f"/projects/{pid}/auth", json={"suite": {**suite, "migration": migration}})

    assert (await patch(body("legacy_read_only"))).status_code == 200
    assert (await patch(body("hub_only"))).status_code == 409  # skips dual
    assert (await patch(body("dual", **DUAL))).status_code == 200
    longer = {"dual_until": (_NOW + timedelta(days=80)).isoformat().replace("+00:00", "Z"), "window_started_at": START}
    assert (await patch(body("dual", **longer))).status_code == 409  # extension refused
    assert (await patch(body("hub_only"))).status_code == 200
    assert (await patch(body("dual", **DUAL))).status_code == 409  # hub_only is final


async def test_dual_window_must_start_now_and_end_within_90_days(client: AsyncClient) -> None:
    pid = await _suite_project(client)
    url = f"/projects/{pid}/suite/migration"
    assert (await client.put(url, json=body("legacy_read_only"))).status_code == 200
    far = {"window_started_at": "2098-11-01T00:00:00Z", "dual_until": "2099-01-01T00:00:00Z"}
    assert (await client.put(url, json=body("dual", **far))).status_code == 409
