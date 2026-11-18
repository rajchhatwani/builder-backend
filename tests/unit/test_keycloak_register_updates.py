"""keycloak_register brings EXISTING protocol mappers and role descriptions in line (F-1052)."""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType
from typing import Any

from app.core.generator import generate
from app.core.spec_models import Spec

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "specs"


def _module() -> ModuleType:
    spec = Spec.model_validate(json.loads((FIX / "authz_keycloak.json").read_text(encoding="utf-8")))
    src = generate(spec)["scripts/keycloak_register.py"]
    mod = ModuleType("kc_reg")
    mod.__file__ = "/tmp/scripts/keycloak_register.py"
    exec(compile(src, "kc_reg", "exec", dont_inherit=True), mod.__dict__)  # noqa: S102
    return mod


def test_existing_mapper_and_role_are_updated_when_changed() -> None:
    mod = _module()
    calls: list[tuple[str, str, Any]] = []
    mapper_old = {"id": "m1", "name": "api-audience", "protocolMapper": "oidc-audience-mapper", "config": {"included.client.audience": "old-api"}}

    def fake(method: str, url: str, token: str | None = None, body: Any = None, form: Any = None, allow_missing: bool = False) -> Any:
        calls.append((method, url, body))
        if method == "GET" and "clientId=" in url:
            return [{"id": "c1", "attributes": {}}], {}
        if method == "GET" and url.endswith("/protocol-mappers/models"):
            return [mapper_old], {}
        if method == "GET" and "/roles/" in url:
            return {"name": "admin", "description": "old"}, {}
        return None, {}

    mod.call = fake
    desired = {"clientId": "b", "protocolMappers": [{"name": "api-audience", "protocolMapper": "oidc-audience-mapper", "config": {"included.client.audience": "new-api"}}]}
    mod.ensure_client("http://kc/admin", "t", desired)
    puts = [c for c in calls if c[0] == "PUT" and "protocol-mappers/models/m1" in c[1]]
    assert puts and puts[0][2]["config"]["included.client.audience"] == "new-api"
    mod.ensure_roles("http://kc/admin", "t", "c1", [{"name": "admin", "description": "new"}])
    assert any(c[0] == "PUT" and c[1].endswith("/roles/admin") and c[2]["description"] == "new" for c in calls)
