"""Suite identity paths (b) join-existing and (c) migration kit, end to end on a real Postgres.

Generated projects run their own tests plus tests/e2e/suite_paths_scenarios.py; the host runs the generated CLI
(`python -m app.auth.export`) as a customer would and exchanges identity-v1 / Keycloak files through a directory.

Path (b): an OLD built-in app (users, an owned row) exports; `keycloak-import` and `impact` run; the project is
regenerated as a suite member with `auth.suite.migration` dual (and, separately, hub_only) in a NEW project and a new
database; the accounts are imported and linked (`relink --copy`); a token the old app issued still works inside the
window and resolves to the same local user as an unexpired hub token; the window expiry and hub_only refuse it.
Path (c): two independent built-in apps with one verified and one unverified e-mail in common: the overlap analyser
reports exactly the verified collision and `link_verified` succeeds only with both proofs from trusted issuers.

Not covered here (no network for the Keycloak stack): the hub token is an RS256 token signed by the generated test key and
verified by the app's real oidc code against a fake JWKS endpoint, not issued by a live Keycloak. Needs Docker (testcontainers).
"""

import json
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

from testcontainers.community.postgres import PostgresContainer

from app.core.generator import generate
from app.core.spec_models import Spec
from tests.e2e.test_generated_project import ok, postgres, run  # noqa: F401

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent / "fixtures" / "specs"
START, END = "2999-01-01T00:00:00Z", "2999-02-15T00:00:00Z"


def _fixture() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / "keycloak_suite.json").read_text(encoding="utf-8"))
    return data


def builtin_spec(slug: str) -> dict[str, Any]:
    """The old app: the suite fixture without Keycloak, with open registration."""
    spec = _fixture()
    spec["project"].update(slug=slug, name=slug.replace("-", " ").title())
    auth = spec["auth"]
    for key in ("provider", "keycloak", "suite"):
        auth.pop(key, None)
    auth["registration"] = {"email_verification_required": False, "invite_only": False}
    auth["password_reset"] = {"email_magic_link": False}
    return spec


def member_spec(state: str) -> dict[str, Any]:
    """The same app, regenerated as a suite member with a migration (new project, same slug and entities)."""
    spec = _fixture()
    spec["auth"]["suite"]["hub_issuer"] = None
    spec["auth"]["suite"]["join_state"] = "joined"
    migration: dict[str, Any] = {"state": state, "legacy_issuer": "builtin:suite-portal"}
    if state == "dual":
        migration.update(window_started_at=START, dual_until=END)
    spec["auth"]["suite"]["migration"] = migration
    return spec


def project(tmp_path_factory: Any, name: str, spec: dict[str, Any]) -> Path:
    root: Path = tmp_path_factory.mktemp(name)
    for path, content in generate(Spec.model_validate(deepcopy(spec))).items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    shutil.copy(HERE / "suite_paths_scenarios.py", root / "tests" / "test_scenarios.py")
    return root


def scenario(postgres: PostgresContainer, root: Path, db: str, out: Path, role: str, **env: str) -> str:  # noqa: F811
    url = (
        f"postgresql+asyncpg://{postgres.username}:{postgres.password}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/{db}_test"
    )
    ok(run(["-m", "tests._prepare_db"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    output = ok(
        run(
            ["-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_scenarios.py", "-k", role.split(":")[0]],
            root,
            url,
            E2E_ROLE=role,
            E2E_OUT=str(out),
            **env,
        )
    )
    assert "1 passed" in output and "failed" not in output, output
    return output


def test_path_b_join_existing_keeps_ids_and_closes_the_legacy_window(
    postgres: PostgresContainer,  # noqa: F811
    tmp_path_factory,  # noqa: ANN001
) -> None:
    out: Path = tmp_path_factory.mktemp("paths_b_out")
    old = project(tmp_path_factory, "b_old", builtin_spec("suite-portal"))
    scenario(postgres, old, "b_old", out, "b_source")

    state = json.loads((out / "state.json").read_text(encoding="utf-8"))
    kc = json.loads((out / "kc.json").read_text(encoding="utf-8"))
    impact = json.loads((out / "impact.json").read_text(encoding="utf-8"))
    raw = "".join((out / name).read_text(encoding="utf-8") for name in ("kc.json", "impact.json", "users.ndjson"))
    for password_hash in state["hashes"]:  # no hash anywhere in what leaves the app
        assert password_hash not in raw and password_hash.split("$")[-1] not in raw
    by_email = {u["email"]: u for u in kc["users"]}
    assert all("credentials" not in u and "UPDATE_PASSWORD" in u["requiredActions"] for u in kc["users"])
    assert by_email["ann@example.com"]["id"] == state["users"]["ann@example.com"]  # Keycloak id = local id
    assert by_email["ann@example.com"]["clientRoles"] == {"suite-portal": ["agent"]}
    assert "VERIFY_EMAIL" in by_email["cy@example.com"]["requiredActions"]
    assert "VERIFY_EMAIL" not in by_email["ann@example.com"]["requiredActions"]
    assert impact["users"] == 3 and impact["unverified"]["count"] == 1
    assert impact["verified_duplicates_with_hub"]["emails"] == ["ann@example.com"]
    assert impact["unverified_with_a_hub_account"] == ["cy@example.com"]

    dual = project(tmp_path_factory, "b_dual", member_spec("dual"))
    scenario(postgres, dual, "b_dual", out, "b_target", E2E_EXPECT="dual")
    hub_only = project(tmp_path_factory, "b_hub_only", member_spec("hub_only"))
    scenario(postgres, hub_only, "b_hub_only", out, "b_target", E2E_EXPECT="hub_only")


def test_path_c_overlap_reports_only_verified_collisions_and_links_need_both_proofs(
    postgres: PostgresContainer,  # noqa: F811
    tmp_path_factory,  # noqa: ANN001
) -> None:
    out: Path = tmp_path_factory.mktemp("paths_c_out")
    one = project(tmp_path_factory, "c_one", builtin_spec("app-one"))
    scenario(postgres, one, "c_one", out, "c_first")
    two = project(tmp_path_factory, "c_two", builtin_spec("app-two"))
    scenario(postgres, two, "c_two", out, "c_second")
    report = json.loads((out / "overlap.json").read_text(encoding="utf-8"))
    assert [c["email"] for c in report["collisions"]] == ["shared@example.com"]
    assert report["modified"] is False
