"""Cross-tenant ids on nested routes: the attacker (own org, own project) names the victim's
workspace/preview/import/report/... id, either under the victim's project or under their own."""

import re

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.api._auth_helpers import make_project
from tests.api._routes import all_routes
from tests.api.conftest import ClientFor
from tests.audit.tenant_rls._world import two_orgs, victim_world

# path-param name -> key in the victim world
PARAMS = {
    "project_id": "project_id", "entity_id": "entity_id", "field_id": "field_id",
    "role_id": "role_id", "permission_id": "role_id", "relation_id": "entity_id",
    "ws_id": "ws_id", "preview_id": "preview_id", "batch_id": "batch_id", "row_id": "row_id",
    "key": "metric_key", "report_id": "report_id", "item_id": "item_id",
    "question_id": "question_id", "request_id": "request_id", "entry_id": "entry_id",
    "run_id": "run_id", "approval_id": "approval_id", "generation_id": "generation_id",
    "token_id": "token_id", "user_id": "user_id", "entity": "entity_name", "name": "title",
    "seq": "seq", "step": "step",
}
SKIP_PREFIXES = ("/admin/", "/orgs", "/account", "/scim/", "/sso", "/billing", "/.well-known")
SKIP = {"/health", "/ready", "/projects"}  # /projects: unscoped create/list (own data only)


def _project_routes() -> list[tuple[str, str]]:
    seen = []
    for r in all_routes():
        if r.path.startswith(SKIP_PREFIXES) or r.path in SKIP or r.path.startswith("/previews/"):
            continue
        seen.append((r.method, r.path))
    return seen


def _fill(template: str, world: dict[str, str], proj: str | None = None) -> str:
    vals = dict(world)
    vals.update(entity_name="Secret", title="title", seq="1", step="intake")
    if proj is not None:
        vals["project_id"] = proj

    def sub(m: re.Match[str]) -> str:
        name = m.group(1).split(":")[0]
        return vals.get(PARAMS.get(name, name), "00000000-0000-4000-8000-000000000001")

    return re.sub(r"{([^}]+)}", sub, template)


async def test_attacker_sweep_every_victim_route_is_404(
    client_for: ClientFor, session_factory: async_sessionmaker  # type: ignore[type-arg]
) -> None:
    """Every project-scoped route, with the victim's project id: 404 for the stranger, never a
    2xx/403/5xx (403 would confirm the project exists)."""
    a, b = await two_orgs(client_for)
    w = await victim_world(a, session_factory)
    bad = []
    for method, tpl in _project_routes():
        path = _fill(tpl, w)
        if path.startswith("/projects") and "/events/stream" in path:
            continue  # streaming: covered separately
        r = await b.request(method, path, json={})
        if r.status_code != 404:
            bad.append(f"{method} {tpl} -> {r.status_code}")
    assert bad == [], "\n".join(bad)


@pytest.fixture
def ws_settings(monkeypatch: pytest.MonkeyPatch, tmp_path, database_url: str):  # noqa: ANN201, ANN001
    """Workspaces configured, so a 503 'not configured' cannot mask the ownership check."""
    from pydantic import SecretStr

    from app.config import Settings
    from app.services import workspace_service

    s = Settings(
        environment="test", workspace_root=str(tmp_path / "ws"),
        workspace_db_admin_url=SecretStr(database_url),
    )
    monkeypatch.setattr(workspace_service, "get_settings", lambda: s)
    return s


async def test_victim_nested_ids_under_attackers_own_project(
    client_for: ClientFor, session_factory: async_sessionmaker,  # type: ignore[type-arg]
    ws_settings: object,
) -> None:
    """Attacker owns project pB; every nested route with pB in the path and the VICTIM's child id
    must answer 404 (the child is not in pB) and must not change the victim's row."""
    a, b = await two_orgs(client_for)
    w = await victim_world(a, session_factory)
    pb = await make_project(b, "Mine")
    nested = {"ws_id", "preview_id", "batch_id", "row_id", "key", "report_id", "item_id",
              "question_id", "request_id", "entry_id", "run_id", "approval_id", "token_id",
              "user_id"}
    bad = []
    for method, tpl in _project_routes():
        names = {m.split(":")[0] for m in re.findall(r"{([^}]+)}", tpl)}
        if "project_id" not in names or not (names & nested):
            continue
        path = _fill(tpl, w, proj=pb)
        r = await b.request(method, path, json={})
        if r.status_code in (200, 201, 202, 204) or r.status_code >= 500:
            bad.append(f"{method} {tpl} -> {r.status_code}")
        elif r.status_code not in (404, 400, 409, 422, 403):
            bad.append(f"{method} {tpl} -> odd {r.status_code}")
    assert bad == [], "\n".join(bad)


async def test_victim_rows_untouched_after_attacks(
    client_for: ClientFor, session_factory: async_sessionmaker  # type: ignore[type-arg]
) -> None:

    from app.models.agent import AiApproval, AiRun
    from app.models.dependency_policy import DependencyRequest
    from app.models.platform import ApiToken
    from app.models.registry import RegistryHookEntry
    from app.models.requirements import RequirementItem, RequirementQuestion
    from tests.audit.tenant_rls._world import uid

    a, b = await two_orgs(client_for)
    w = await victim_world(a, session_factory)
    pb = await make_project(b, "Mine")
    attacks = [
        ("POST", f"/projects/{pb}/dependencies/requests/{w['request_id']}/approve"),
        ("POST", f"/projects/{pb}/dependencies/requests/{w['request_id']}/deny"),
        ("POST", f"/projects/{pb}/registry/hooks/{w['entry_id']}/approve"),
        ("POST", f"/projects/{pb}/agent/runs/{w['run_id']}/cancel"),
        ("POST", f"/projects/{pb}/agent/approvals/{w['approval_id']}/decision"),
        ("DELETE", f"/projects/{pb}/tokens/{w['token_id']}"),
        ("DELETE", f"/account/tokens/{w['token_id']}"),
        ("POST", f"/projects/{pb}/requirements/questions/{w['question_id']}/answer"),
        ("PUT", f"/projects/{pb}/requirements/items/{w['item_id']}"),
    ]
    bodies = {"decision": {"decision": "approve"}, "answer": {"answer": "pwned"},
              "items": {"status": "covered", "covered_by": "pwned"}}
    for method, path in attacks:
        body = next((v for k, v in bodies.items() if k in path), {})
        r = await b.request(method, path, json=body)
        assert r.status_code != 200 and r.status_code != 204, f"{method} {path} -> {r.status_code}"
    async with session_factory() as s:
        assert (await s.get(DependencyRequest, uid(w["request_id"]))).status == "pending"
        assert (await s.get(RegistryHookEntry, uid(w["entry_id"]))).approved_by is None
        assert (await s.get(AiRun, uid(w["run_id"]))).state == "running"
        assert (await s.get(AiApproval, uid(w["approval_id"]))).state == "pending"
        assert (await s.get(ApiToken, uid(w["token_id"]))).revoked_at is None
        assert (await s.get(RequirementQuestion, uid(w["question_id"]))).answer is None
        assert (await s.get(RequirementItem, uid(w["item_id"]))).status == "open"
