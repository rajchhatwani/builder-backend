"""B1-023: shell/seed script fixes (F-0494..F-0499)."""

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def _bash(code: str, env: dict | None = None) -> str:
    r = subprocess.run(
        ["bash", "-c", code], capture_output=True, text=True, env={**os.environ, **(env or {})}
    )
    return r.stdout.strip()


def test_f0494_budget_keep_never_lowers_existing_grant(tmp_path):
    f = tmp_path / "b"
    env = {"BB_MODEL_BUDGET_FILE": str(f), "ROOT": str(tmp_path)}
    out = _bash(
        f". {SCRIPTS}/model_budget.sh; budget_alloc manual 2680000 >/dev/null;"
        "budget_alloc manual 4500000 >/dev/null; budget_keep manual 2680000;"
        "budget_alloc showcase 5000000",
        env,
    )
    assert out.splitlines() == ["4500000", "500000"]
    assert "budget_keep manual" in (SCRIPTS / "manual_stack.sh").read_text()


def test_f0495_golive_skips_firewall_without_root():
    s = (SCRIPTS / "golive_check.sh").read_text()
    assert "id -u" in s and "SKIP" in s


def test_f0496_showcase_start_guards_running_api_and_has_restart():
    s = (SCRIPTS / "showcase_stack.sh").read_text()
    assert "restart-api" in s
    assert "pid_alive" in s


def test_f0499_showcase_stop_verifies_port_owner():
    s = (SCRIPTS / "showcase_stack.sh").read_text()
    stop = s[s.index("  stop)") : s.index("  status)")]
    assert "uvicorn" in stop and "vite" in stop


def _load_seed():
    spec = importlib.util.spec_from_file_location("seed_mod", SCRIPTS / "seed.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["seed_mod"] = m
    spec.loader.exec_module(m)
    return m


OPENAPI = json.loads((ROOT / "frontend/e2e/openapi.json").read_text())


def _body_schema(method: str, path: str):
    path = path.split("?")[0]
    for tpl, item in OPENAPI["paths"].items():
        if re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", tpl), path) and method.lower() in item:
            c = item[method.lower()].get("requestBody", {}).get("content", {})
            return c.get("application/json", {}).get("schema"), True
    return None, False


class FakeApi:
    def __init__(self, seed, fail_on=None):
        self.base, self.token, self.n, self.calls = "http://x", "t", 0, []
        self.fail_on, self.deleted, self.created = fail_on, [], []

    def call(self, method, path, body=None, authenticated=True):
        if self.fail_on and self.fail_on in path:
            raise SystemExit(f"{method} {path} -> 422")
        self.calls.append((method, path))
        if method == "GET":
            return {
                "items": [{"slug": s, "id": f"id-{s}"} for s in self.created]
                + [{"slug": "sso-hub", "id": "hub"}]
            }
        if method == "DELETE":
            self.deleted.append(path)
            return None
        if body is not None:
            schema, found = _body_schema(method, path)
            assert found, f"{method} {path} not in OpenAPI snapshot"
            if schema:
                jsonschema.validate(
                    body,
                    {**schema, "components": OPENAPI["components"]},
                )
        if method == "POST" and path == "/projects":
            self.created.append(body["slug"])
            return {"id": f"id-{body['slug']}"}
        self.n += 1
        if path.endswith("/validate"):
            return {"valid": True, "issues": []}
        return {"id": f"i{self.n}"}

    get = lambda self, p: self.call("GET", p)  # noqa: E731
    post = lambda self, p, b=None: self.call("POST", p, b)  # noqa: E731
    put = lambda self, p, b: self.call("PUT", p, b)  # noqa: E731
    patch = lambda self, p, b: self.call("PATCH", p, b)  # noqa: E731
    delete = lambda self, p: self.call("DELETE", p)  # noqa: E731


def test_f0498_every_seed_builder_matches_openapi_schemas():
    seed = _load_seed()
    for slug, build in seed.PROJECTS.items():
        api = FakeApi(seed)
        build(api)  # fake validates every body against the snapshot


def test_f0497_failed_build_removes_half_built_project():
    seed = _load_seed()
    api = FakeApi(seed, fail_on="/roles")
    with pytest.raises(SystemExit):
        seed.build_or_cleanup(api, "helpdesk", seed.PROJECTS["helpdesk"])
    assert api.deleted == ["/projects/id-helpdesk"]
